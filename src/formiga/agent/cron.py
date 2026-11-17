"""Tarefas agendadas (cron) — Fase 7 do PRD v2.

Modelo de dados (`Job`), persistência atômica em `~/.formiga/jobs.json` e
cálculo de `next_run` para schedules cron / intervalo / one-shot.

O relógio é injetável (`now_fn`) para que testes determinísticos controlem a
passagem do tempo sem depender do relógio real do sistema.

Não importa nada do `agent/` núcleo (exceto `Config` para defaults de
orçamento). O scheduler propriamente dito vive no daemon (`gateway.py`).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from croniter import croniter

from formiga.configfile import global_config_path
from formiga.storage import _atomic_write

_GLOBAL_DIR = global_config_path().parent
JOBS_FILE = _GLOBAL_DIR / "jobs.json"

_CATCHUP_SKIP = "skip"
_CATCHUP_ONCE = "once"
_VALID_CATCHUP = frozenset({_CATCHUP_SKIP, _CATCHUP_ONCE})

# Schedule "every 30m" / "every 2h" / "every 1d".
_INTERVAL_RE = __import__("re").compile(
    r"^every\s+(\d+)\s*([mhd])$", __import__("re").IGNORECASE
)


def utc_now() -> datetime:
    """Relógio real do sistema (UTC). Usado como `now_fn` padrão."""
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    """Serializa datetime em ISO-8601 UTC com sufixo Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    """Deserializa ISO-8601 (aceita sufixo Z ou offset)."""
    texto = value.strip()
    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"
    dt = datetime.fromisoformat(texto)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------- #
# Job\n# ---------------------------------------------------------------------- #


@dataclass
class Job:
    """Uma tarefa agendada."""

    id: str
    prompt: str
    schedule: str
    enabled: bool = True
    model: str | None = None
    profile: str | None = None
    max_turns: int | None = None
    max_llm_calls: int | None = None
    timeout_seconds: float | None = None
    catchup: str = _CATCHUP_SKIP
    tz: str | None = None
    next_run: str | None = None
    last_run: str | None = None
    last_status: str | None = None  # "ok" | "error" | "skip" | "catchup" | None
    last_error: str | None = None
    output_dir: str | None = None

    def __post_init__(self) -> None:
        if self.catchup not in _VALID_CATCHUP:
            raise ValueError(
                f"catchup inválido: {self.catchup!r} (use 'skip' ou 'once')."
            )


@dataclass
class JobStore:
    """Persistência de `jobs.json` (atômica, crash-durable)."""

    path: Path = field(default=JOBS_FILE)

    def load(self) -> dict[str, Job]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        jobs: dict[str, Job] = {}
        for job_id, data in payload.items():
            if not isinstance(data, dict):
                continue
            jobs[job_id] = Job(**data)
        return jobs

    def save(self, jobs: dict[str, Job]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {jid: asdict(job) for jid, job in jobs.items()}
        _atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))


# ---------------------------------------------------------------------- #
# Schedules\n# ---------------------------------------------------------------------- #


class Schedule:
    """Uma expressão de schedule com cálculo de `next_run`."""

    def __init__(self, expression: str) -> None:
        self.expression = expression
        self._kind: str  # "cron" | "interval" | "at"
        self._interval: timedelta | None = None
        self._at: datetime | None = None
        self._parse()

    # -- parsing ------------------------------------------------------- #

    def _parse(self) -> None:
        expr = self.expression.strip()

        # one-shot: at 2026-12-01T09:00
        if expr.lower().startswith("at "):
            self._kind = "at"
            try:
                self._at = _parse_iso(expr[3:].strip())
            except ValueError as exc:
                raise ValueError(
                    f"Schedule one-shot inválido: {expr!r} (use 'at <ISO-8601>')."
                ) from exc
            return

        # intervalo: every 30m / every 2h / every 1d
        m = _INTERVAL_RE.match(expr)
        if m:
            self._kind = "interval"
            valor = int(m.group(1))
            unidade = m.group(2).lower()
            if unidade == "m":
                self._interval = timedelta(minutes=valor)
            elif unidade == "h":
                self._interval = timedelta(hours=valor)
            else:
                self._interval = timedelta(days=valor)
            return

        # cron 5 campos
        partes = expr.split()
        if len(partes) != 5:
            raise ValueError(
                f"Schedule inválido: {expr!r} "
                "(use 'cron 5 campos', 'every N[mhd]' ou 'at <ISO-8601>')."
            )
        # Valida a expressão criando um croniter temporário (não guarda estado).
        try:
            croniter(expr)
        except Exception as exc:  # croniter levanta CroniterBadCronError etc.
            raise ValueError(f"Expressão cron inválida: {expr!r} ({exc}).") from exc
        self._kind = "cron"

    # -- cálculo ------------------------------------------------------- #

    def next_run(
        self, after: datetime | None, now_fn: Callable[[], datetime] = utc_now
    ) -> datetime | None:
        """Próxima execução estritamente após `after` (ou agora se None).

        Para `at` one-shot devolve o horário se ainda no futuro, senão None
        (job executado uma vez e não se repete).
        """
        agora = now_fn() if after is None else after
        if agora.tzinfo is None:
            agora = agora.replace(tzinfo=UTC)
        agora = agora.astimezone(UTC)

        if self._kind == "cron":
            # Cria um croniter fresco a cada chamada para não manter estado
            # interno (croniter avança o cursor a cada get_next).
            cron = croniter(self.expression, start_time=agora, ret_type=datetime)
            return cron.get_next(datetime)

        if self._kind == "interval":
            assert self._interval is not None
            return agora + self._interval

        # one-shot "at": só dispara se ainda no futuro.
        assert self._at is not None
        if self._at > agora:
            return self._at
        return None

    def is_due(self, agora: datetime) -> bool:
        """True se o schedule já deveria ter disparado até `agora`."""
        if agora.tzinfo is None:
            agora = agora.replace(tzinfo=UTC)
        agora = agora.astimezone(UTC)
        if self._kind == "at":
            assert self._at is not None
            return agora >= self._at
        return False


def novo_id() -> str:
    """Gera um id curto e determinístico o suficiente para jobs."""
    return uuid.uuid4().hex[:8]


def job_id_da_prompt(prompt: str) -> str:
    """Id derivado do prompt (útil para dedup opcional)."""
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8]


def criar_job(
    prompt: str,
    schedule: str,
    *,
    id: str | None = None,
    enabled: bool = True,
    model: str | None = None,
    profile: str | None = None,
    max_turns: int | None = None,
    max_llm_calls: int | None = None,
    timeout_seconds: float | None = None,
    catchup: str = _CATCHUP_SKIP,
    tz: str | None = None,
    output_dir: str | None = None,
    now_fn: Callable[[], datetime] = utc_now,
) -> Job:
    """Constrói um `Job` e calcula seu primeiro `next_run`."""
    schedule_obj = Schedule(schedule)
    primeiro = schedule_obj.next_run(None, now_fn=now_fn)
    return Job(
        id=id or novo_id(),
        prompt=prompt,
        schedule=schedule,
        enabled=enabled,
        model=model,
        profile=profile,
        max_turns=max_turns,
        max_llm_calls=max_llm_calls,
        timeout_seconds=timeout_seconds,
        catchup=catchup,
        tz=tz,
        next_run=_iso(primeiro) if primeiro is not None else None,
        last_run=None,
        last_status=None,
        last_error=None,
        output_dir=output_dir,
    )


def proxima_execucao(job: Job, now_fn: Callable[[], datetime] = utc_now) -> datetime | None:
    """Recalcula `next_run` a partir do último `next_run` (ou agora)."""
    referencia = _parse_iso(job.next_run) if job.next_run else None
    schedule_obj = Schedule(job.schedule)
    proximo = schedule_obj.next_run(referencia, now_fn=now_fn)
    return proximo
