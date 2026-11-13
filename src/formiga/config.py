"""Configuration loading with explicit precedence.

Highest first: CLI overrides, environment (``FORMIGA_*``), project file
(``./.formiga.toml``), user file (``~/.formiga/config.toml``), built-in defaults.

Config is parsed with :mod:`tomllib` and validated by hand so the core keeps to
``dataclasses`` only. Layouts are data: a layout is one or two endpoints, and ``single``
and ``dual`` differ only in what the mapping contains.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, get_type_hints

from formiga.research.contract import CITATION_STYLES, DEFAULT_PROFILE, PROFILE_NAMES

CONFIG_FILENAME = "config.toml"
PROJECT_CONFIG_FILENAME = ".formiga.toml"
ENV_PREFIX = "FORMIGA_"

#: Top-level tables and keys of the pre-v5 config format. Seeing any of them means the
#: file was written by an older build and must be migrated, not silently half-read.
LEGACY_TOP_LEVEL = frozenset({"geral", "saida", "llm", "corpus", "modelo", "endpoint"})

LAYOUT_NAMES = ("single", "dual", "single-strong", "proxy")
ToolCallFormat = Literal["native", "text", "none"]
TEAMPERATURE_ROLES = ("router", "planner", "reader", "synthesizer", "answerer")
DEFAULT_ROLE_TEMPERATURES: dict[str, float] = {
    "router": 0.2,
    "planner": 0.0,
    "reader": 0.0,
    "synthesizer": 0.3,
    "answerer": 0.4,
}


class ConfigError(ValueError):
    """Raised when configuration cannot be read or validated."""

    def __init__(self, message: str, *, source: Path | None = None) -> None:
        self.source = source
        self.reason = message
        super().__init__(f"{source}: {message}" if source else message)


def _coerce(cls: type, data: dict[str, Any], *, source: Path | None, prefix: str = "") -> Any:
    """Build a dataclass from ``data``, rejecting unknown keys.

    Nested sections are validated by recursion; an unknown key is a hard error because a
    silently ignored typo in a deadline is worse than a refused start.
    """
    known = {f.name: f for f in fields(cls)}
    hints = get_type_hints(cls)
    unknown = set(data) - set(known)
    if unknown:
        where = f"{prefix}{cls.__name__}"
        raise ConfigError(f"unknown key(s) in {where}: {sorted(unknown)}", source=source)
    kwargs: dict[str, Any] = {}
    for name, value in data.items():
        annotation = hints[name]
        inner = _optional_inner(annotation)
        if inner is not None:
            if value is None:
                kwargs[name] = None
                continue
            if not isinstance(value, dict):
                raise ConfigError(f"{prefix}{name} must be a table", source=source)
            kwargs[name] = _coerce(inner, value, source=source, prefix=f"{prefix}{name}.")
            continue
        if isinstance(annotation, type) and hasattr(annotation, "__dataclass_fields__"):
            if not isinstance(value, dict):
                raise ConfigError(f"{prefix}{name} must be a table", source=source)
            kwargs[name] = _coerce(annotation, value, source=source, prefix=f"{prefix}{name}.")
            continue
        if name == "temperature":
            kwargs[name] = _temperatures(value, source=source)
            continue
        kwargs[name] = value
    return cls(**kwargs)


def _optional_inner(annotation: Any) -> type | None:
    """Return ``T`` for ``Optional[T]`` when ``T`` is a dataclass."""
    import types
    from typing import Union, get_args, get_origin

    origin = get_origin(annotation)
    if origin is not Union and origin is not types.UnionType:
        return None
    args = [arg for arg in get_args(annotation) if arg is not type(None)]
    if len(args) != 1:
        return None
    inner = args[0]
    return inner if isinstance(inner, type) and hasattr(inner, "__dataclass_fields__") else None


def _temperatures(value: Any, *, source: Path | None) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ConfigError("temperature must be a table", source=source)
    unknown = set(value) - set(TEAMPERATURE_ROLES)
    if unknown:
        raise ConfigError(f"unknown temperature role(s): {sorted(unknown)}", source=source)
    merged = dict(DEFAULT_ROLE_TEMPERATURES)
    merged.update({name: _as_float(value[name], name, source=source) for name in value})
    return merged


def _as_float(value: Any, name: str, *, source: Path | None) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number", source=source) from exc


@dataclass
class Endpoint:
    """One ``llama-server`` endpoint and the roles it serves."""

    endpoint: str = "http://127.0.0.1:8080"
    model: str | None = None
    context: int = 4096
    tool_call_format: ToolCallFormat = "text"
    supports_grammar: bool = True
    temperature: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_ROLE_TEMPERATURES)
    )
    rung_ceiling: str = "bounded-edit"
    max_context_safe: int = 3072
    request_timeout_s: float = 180.0

    def temperature_for(self, role: str) -> float:
        return self.temperature.get(role, DEFAULT_ROLE_TEMPERATURES.get(role, 0.0))


@dataclass
class Layout:
    """The endpoint mapping. ``fast`` always exists; ``strong`` may alias it."""

    name: str = "single"
    fast: Endpoint = field(default_factory=Endpoint)
    strong: Endpoint | None = None

    @property
    def tiers(self) -> dict[str, Endpoint]:
        tiers = {"fast": self.fast}
        if self.strong is not None:
            tiers["strong"] = self.strong
        return tiers

    def is_single(self) -> bool:
        strong = self.strong
        if strong is None:
            return True
        return strong.endpoint.rstrip("/") == self.fast.endpoint.rstrip("/")

    def rung_ceiling(self) -> str:
        """The lowest ceiling across tiers wins; a layout never over-promises."""
        from formiga.research.report import RUNG_ORDER

        ceilings = [endpoint.rung_ceiling for endpoint in self.tiers.values()]
        return min(ceilings, key=RUNG_ORDER.index)


@dataclass
class ReportSettings:
    """The document contract knobs."""

    profile: str = DEFAULT_PROFILE
    citation_style: str = "apa"
    bilingual: bool = False
    max_quote_chars: int = 400
    max_quote_chars_per_source: int = 900
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class ChatSettings:
    context_budget_ratio: float = 0.6
    keep_turns: int = 4


@dataclass
class BudgetSettings:
    """Optional overrides; the profile's row is the default source of truth."""

    max_llm_calls: int | None = None
    max_prompt_tokens: int | None = None
    max_output_tokens: int | None = None
    deadline_s: float | None = None


@dataclass
class Paths:
    """Resolved filesystem locations, never read from the config file."""

    home: Path
    config: Path
    db: Path
    cache: Path
    reports: Path
    runs: Path
    logs: Path
    skills: Path
    memory: Path


@dataclass
class Settings:
    """Validated application settings."""

    language: str = "en"
    output_language: str = "en"
    search_languages: list[str] = field(default_factory=lambda: ["en"])
    mode: Literal["research", "plan"] = "research"
    layout: Layout = field(default_factory=Layout)
    report: ReportSettings = field(default_factory=ReportSettings)
    chat: ChatSettings = field(default_factory=ChatSettings)
    budget: BudgetSettings = field(default_factory=BudgetSettings)
    paths: Paths = field(default_factory=lambda: _paths_for(default_home()))
    allow_heavy: bool = False

    def profile_spec(self):
        """Return the configured default profile with any TOML overrides applied."""
        from formiga.research.contract import get_profile

        return get_profile(self.report.profile, overrides=self.report.profiles)


def default_home() -> Path:
    """Return the application home, honouring ``XDG_DATA_HOME``."""
    override = os.environ.get(f"{ENV_PREFIX}HOME")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "formiga"
    return Path.home() / ".formiga"


def reports_home() -> Path:
    """Return the reports directory (``~/formiga/reports`` unless overridden)."""
    override = os.environ.get(f"{ENV_PREFIX}REPORTS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "formiga" / "reports"


def user_config_path(home: Path | None = None) -> Path:
    return (home or default_home()) / CONFIG_FILENAME


def project_config_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / PROJECT_CONFIG_FILENAME


def _paths_for(home: Path) -> Paths:
    return Paths(
        home=home,
        config=home / CONFIG_FILENAME,
        db=home / "formiga.db",
        cache=home / "cache",
        reports=reports_home(),
        runs=home / "runs",
        logs=home / "logs",
        skills=home / "skills",
        memory=home / "memory.md",
    )


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}", source=path) from exc
    except OSError as exc:
        raise ConfigError(str(exc), source=path) from exc
    if not isinstance(data, dict):
        raise ConfigError("top-level value must be a table", source=path)
    legacy = LEGACY_TOP_LEVEL & set(data)
    if legacy:
        raise ConfigError(
            "legacy config format (found "
            + ", ".join(sorted(legacy))
            + "); move it aside and run `formiga init`",
            source=path,
        )
    return data


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``overlay`` onto ``base`` without mutating either."""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge(current, value)
        else:
            merged[key] = value
    return merged


def _env_overrides(environ: dict[str, str]) -> dict[str, Any]:
    """Map ``FORMIGA_*`` variables onto settings sections."""
    mapping = {
        "LANGUAGE": ("language",),
        "OUTPUT_LANGUAGE": ("output_language",),
        "MODE": ("mode",),
        "PROFILE": ("report", "profile"),
        "LAYOUT": ("layout", "name"),
        "ENDPOINT": ("layout", "fast", "endpoint"),
        "MODEL": ("layout", "fast", "model"),
        "RUNG_CEILING": ("layout", "fast", "rung_ceiling"),
    }
    overrides: dict[str, Any] = {}
    for env_key, path in mapping.items():
        value = environ.get(f"{ENV_PREFIX}{env_key}")
        if not value:
            continue
        cursor = overrides
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = value
    if environ.get(f"{ENV_PREFIX}ALLOW_HEAVY", "").lower() in {"1", "true", "yes"}:
        overrides["allow_heavy"] = True
    return overrides


def _validate(settings: Settings, *, source: Path | None) -> Settings:
    if settings.language not in _available_locales():
        raise ConfigError(f"unknown UI language: {settings.language}", source=source)
    if settings.layout.name not in LAYOUT_NAMES:
        raise ConfigError(f"unknown layout: {settings.layout.name}", source=source)
    if settings.report.profile not in PROFILE_NAMES:
        raise ConfigError(f"unknown profile: {settings.report.profile}", source=source)
    if settings.report.citation_style not in CITATION_STYLES:
        raise ConfigError(
            f"unknown citation style: {settings.report.citation_style}", source=source
        )
    return settings


def _available_locales() -> tuple[str, ...]:
    from formiga.i18n import available_locales

    return tuple(available_locales()) or ("en",)


def load_settings(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
    environ: dict[str, str] | None = None,
) -> Settings:
    """Load, merge and validate settings for one invocation."""
    resolved_home = home or default_home()
    data: dict[str, Any] = {}
    for path in (user_config_path(resolved_home), project_config_path(cwd)):
        data = _merge(data, _read_toml(path))
    data = _merge(data, _env_overrides(dict(environ if environ is not None else os.environ)))
    data = _merge(data, _clean_overrides(cli_overrides or {}))
    data.pop("paths", None)
    data.pop("allow_heavy", None)

    sections = dict(data)
    layout_data = sections.pop("layout", {})
    layout = _coerce(Layout, layout_data, source=None)
    settings = Settings(
        layout=layout,
        report=_coerce(ReportSettings, sections.pop("report", {}), source=None),
        chat=_coerce(ChatSettings, sections.pop("chat", {}), source=None),
        budget=_coerce(BudgetSettings, sections.pop("budget", {}), source=None),
        paths=_paths_for(resolved_home),
        allow_heavy=bool((cli_overrides or {}).get("allow_heavy")),
        **_scalar_sections(sections),
    )
    search_languages = sections.pop("search_languages", None)
    unexpected = set(sections) - {"language", "output_language", "mode"}
    if unexpected:
        raise ConfigError(
            "unknown top-level key(s): " + ", ".join(sorted(unexpected))
            + (f" (config file: {user_config_path(resolved_home)})" if
               user_config_path(resolved_home).exists() else ""),
            source=user_config_path(resolved_home)
            if user_config_path(resolved_home).exists() else None,
        )
    if "output_language" not in sections:
        settings.output_language = settings.language
    if search_languages:
        if not isinstance(search_languages, list):
            raise ConfigError("search_languages must be an array", source=None)
        settings.search_languages = [str(item) for item in search_languages]
    else:
        settings.search_languages = [settings.language]
    return _validate(settings, source=None)


def _scalar_sections(sections: dict[str, Any]) -> dict[str, Any]:
    """Top-level scalars that :class:`Settings` accepts directly."""
    names = {"language", "output_language", "mode"}
    return {key: value for key, value in sections.items() if key in names}


def _clean_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    """Drop ``None`` values so an unset CLI flag never erases a file setting."""
    cleaned: dict[str, Any] = {}
    for key, value in overrides.items():
        if value is None:
            continue
        if isinstance(value, dict):
            nested = _clean_overrides(value)
            if nested:
                cleaned[key] = nested
            continue
        cleaned[key] = value
    return cleaned


__all__ = [
    "CONFIG_FILENAME",
    "DEFAULT_ROLE_TEMPERATURES",
    "ENV_PREFIX",
    "LAYOUT_NAMES",
    "PROJECT_CONFIG_FILENAME",
    "BudgetSettings",
    "ChatSettings",
    "ConfigError",
    "Endpoint",
    "Layout",
    "Paths",
    "ReportSettings",
    "Settings",
    "default_home",
    "load_settings",
    "project_config_path",
    "reports_home",
    "user_config_path",
]
