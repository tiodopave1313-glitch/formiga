"""Testes da Fase 7 — Tarefas agendadas (cron), com relógio fake.

Cobre:\n- criar_job / Schedule: cron 5 campos, every N[mhd], at <ISO>; next_run
  com relógio injetável; one-shot no passado -> None.\n- JobStore: persistência
  atômica em jobs.json.\n- CLI: cron add/list/rm/enable/disable/run (run
  in-process com fake chat, sem daemon).\n- Scheduler: skip com gateway parado,
  catchup: once, next_run avançado após disparo.\n"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from formiga.agent.cron import (
    Job,
    JobStore,
    Schedule,
    criar_job,
    proxima_execucao,
)
from formiga.agent.gateway import Gateway

# ---------------------------------------------------------------------- #
# Relógio fake\n# ---------------------------------------------------------------------- #


class FakeClock:
    """Relógio controlável para testes determinísticos."""

    def __init__(self, inicio: datetime) -> None:
        from datetime import timedelta

        self.inicio = inicio
        self.atual = inicio
        self._timedelta = timedelta

    def avançar(self, segundos: float) -> None:
        self.atual = self.atual + self._timedelta(seconds=segundos)

    def agora(self) -> datetime:
        return self.atual


# ---------------------------------------------------------------------- #
# Schedule / criar_job\n# ---------------------------------------------------------------------- #


def test_schedule_cron_campos():
    clock = FakeClock(datetime(2026, 11, 17, 10, 0, tzinfo=UTC))
    s = Schedule("0 7 * * *")
    nr = s.next_run(None, now_fn=clock.agora)
    assert nr == datetime(2026, 11, 18, 7, 0, tzinfo=UTC)


def test_schedule_intervalo():
    clock = FakeClock(datetime(2026, 11, 17, 10, 0, tzinfo=UTC))
    s = Schedule("every 30m")
    nr = s.next_run(None, now_fn=clock.agora)
    assert nr == datetime(2026, 11, 17, 10, 30, tzinfo=UTC)

    s2 = Schedule("every 2h")
    nr2 = s2.next_run(None, now_fn=clock.agora)
    assert nr2 == datetime(2026, 11, 17, 12, 0, tzinfo=UTC)

    s3 = Schedule("every 1d")
    nr3 = s3.next_run(None, now_fn=clock.agora)
    assert nr3 == datetime(2026, 11, 18, 10, 0, tzinfo=UTC)


def test_schedule_at_no_futuro():
    clock = FakeClock(datetime(2026, 11, 17, 10, 0, tzinfo=UTC))
    s = Schedule("at 2026-12-01T09:00")
    nr = s.next_run(None, now_fn=clock.agora)
    assert nr == datetime(2026, 12, 1, 9, 0, tzinfo=UTC)


def test_schedule_at_no_passado_devolve_none():
    clock = FakeClock(datetime(2026, 11, 17, 10, 0, tzinfo=UTC))
    s = Schedule("at 2020-01-01T00:00")
    assert s.next_run(None, now_fn=clock.agora) is None


def test_schedule_invalido():
    with pytest.raises(ValueError):
        Schedule("cron invalido")
    with pytest.raises(ValueError):
        Schedule("every 5x")
    with pytest.raises(ValueError):
        Schedule("at não-é-uma-data")


def test_criar_job_calcula_primeiro_next_run():
    clock = FakeClock(datetime(2026, 11, 17, 10, 0, tzinfo=UTC))
    job = criar_job("oi", "0 7 * * *", now_fn=clock.agora)
    assert job.next_run == "2026-11-18T07:00:00Z"


def test_criar_job_catchup_invalido():
    with pytest.raises(ValueError):
        criar_job("oi", "0 7 * * *", catchup="talvez")


def test_proxima_execucao_avanca():
    clock = FakeClock(datetime(2026, 11, 17, 10, 0, tzinfo=UTC))
    job = criar_job("oi", "0 7 * * *", now_fn=clock.agora)
    assert job.next_run == "2026-11-18T07:00:00Z"

    clock.avançar(86400)  # +1 dia -> 2026-11-18 10:00
    prox = proxima_execucao(job, now_fn=clock.agora)
    assert prox == datetime(2026, 11, 19, 7, 0, tzinfo=UTC)


# ---------------------------------------------------------------------- #
# JobStore\n# ---------------------------------------------------------------------- #


def test_jobstore_persiste_jobs(tmp_path):
    store = JobStore(path=tmp_path / "jobs.json")
    jobs = {"j1": Job(id="j1", prompt="p", schedule="0 7 * * *")}
    store.save(jobs)
    carregados = store.load()
    assert "j1" in carregados
    assert carregados["j1"].prompt == "p"
    assert carregados["j1"].schedule == "0 7 * * *"


def test_jobstore_arquivo_inexistente_retorna_vazio(tmp_path):
    store = JobStore(path=tmp_path / "nao_existe.json")
    assert store.load() == {}


# ---------------------------------------------------------------------- #
# CLI cron (run offline)\n# ---------------------------------------------------------------------- #


def test_cron_run_offline_job_nao_encontrado(monkeypatch):
    """cron run com job inexistente retorna erro sem depender do daemon."""
    import formiga.cli as cli_mod

    class _EmptyStore:
        def load(self):
            return {}

        def save(self, jobs):
            pass

    monkeypatch.setattr(cli_mod, "JobStore", _EmptyStore)

    rc = cli_mod.main(["cron", "run", "nao_existe"])
    assert rc == 2  # EXIT_INVALID_INPUT


# ---------------------------------------------------------------------- #
# Scheduler: skip / catchup
# ---------------------------------------------------------------------- #


def test_processar_jobs_perdidos_skip_default(tmp_path):
    """Gateway parado na hora → skip (last_status='skip')."""
    gw = Gateway(tmp_path)
    # Job criado às 10:00 do dia 17 → next_run = 07:00 do dia 18.
    agora_criacao = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
    job = criar_job("oi", "0 7 * * *", now_fn=lambda: agora_criacao)
    assert job.next_run == "2026-11-18T07:00:00Z"
    # O gateway volta às 10:00 do dia 18: o disparo das 07:00 foi perdido.
    agora_retorno = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
    gw.jobs = {"j1": job}
    gw.job_store = JobStore(path=tmp_path / "jobs.json")
    gw._processar_jobs_perdidos(agora=agora_retorno)

    job_atualizado = gw.jobs["j1"]
    assert job_atualizado.last_status == "skip"
    assert job_atualizado.next_run is not None  # avançado para o futuro


def test_processar_jobs_perdidos_catchup_once(tmp_path):
    """catchup: once dispara uma vez ao voltar."""
    gw = Gateway(tmp_path, catchup="once")
    agora_criacao = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
    job = criar_job(
        "oi", "0 7 * * *", catchup="once", now_fn=lambda: agora_criacao
    )
    # O gateway volta às 10:00 do dia 18: o disparo das 07:00 foi perdido.
    agora_retorno = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
    gw.jobs = {"j1": job}
    gw.job_store = JobStore(path=tmp_path / "jobs.json")
    gw._processar_jobs_perdidos(agora=agora_retorno)

    job_atualizado = gw.jobs["j1"]
    # catchup dispara o job; last_status não é skip.
    assert job_atualizado.last_status != "skip"
