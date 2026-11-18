"""Descoberta determinística e isolamento de falhas de extensões."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

from formiga.agent.extensions.registry import ExtensionContext, ExtensionRecord, ExtensionRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

    from formiga.agent.session import Session
    from formiga.config import Config


@dataclass(frozen=True)
class ExtensionCandidate:
    name: str
    source: str
    loader: Callable[[], object]


def project_root(config: Config) -> Path:
    """Diretório usado para resolver `.formiga/extensions` e trust."""
    return Path(getattr(config, "agent_workdir", ".")).expanduser().resolve()


def global_trusted_projects(home: Path | None = None) -> set[Path]:
    """Lê allowlist exclusivamente de ~/.formiga/config.toml."""
    home = home or Path.home()
    path = home / ".formiga" / "config.toml"
    if not path.is_file():
        return set()
    try:
        import tomllib

        with path.open("rb") as stream:
            data = tomllib.load(stream)
        configured = data.get("extensions", {}).get("trusted_projects", [])
    except (OSError, ValueError, AttributeError):
        return set()
    if not isinstance(configured, list):
        return set()
    trusted: set[Path] = set()
    for item in configured:
        if isinstance(item, str) and item.strip():
            candidate = Path(item).expanduser()
            if not candidate.is_absolute():
                candidate = home / candidate
            trusted.add(candidate.resolve())
    return trusted


def discover_extensions(
    config: Config,
    session: Session,
    registry: ExtensionRegistry,
    *,
    root: Path | None = None,
    home: Path | None = None,
) -> tuple[ExtensionRecord, ...]:
    """Carrega builtin, entry-points, globais e projeto em ordem definida."""
    root = (root or project_root(config)).resolve()
    home = (home or Path.home()).resolve()
    candidates: list[ExtensionCandidate] = []

    builtin_names = {"core", "web", "deepsearch", "memory"}
    enabled = tuple(getattr(config, "extensions_enabled", ("core", "web", "deepsearch")))
    unknown = set(enabled) - builtin_names
    if unknown:
        raise ValueError(f"extensões builtin desconhecidas: {sorted(unknown)}")
    # Ordem de carga = ordem da lista `enabled` (determinística e controlada
    # pelo usuário), não uma ordem fixa do código.
    for name in enabled:
        candidates.append(
            ExtensionCandidate(
                name,
                "builtin",
                lambda name=name: __import__(f"formiga.ext.{name}", fromlist=["setup"]),
            )
        )

    try:
        points = importlib.metadata.entry_points(group="formiga.extensions")
    except TypeError:  # compatibilidade com versões antigas do importlib.metadata
        points = importlib.metadata.entry_points().select(group="formiga.extensions")
    for point in sorted(points, key=lambda item: item.name):
        candidates.append(
            ExtensionCandidate(point.name, "pip", lambda point=point: point.load())
        )

    global_dir = home / ".formiga" / "extensions"
    candidates.extend(_file_candidates(global_dir, "global"))

    project_dir = root / ".formiga" / "extensions"
    if project_dir.is_dir() and root in global_trusted_projects(home):
        candidates.extend(_file_candidates(project_dir, "project"))

    loaded_names = {record.name for record in registry.extensions}
    for order, candidate in enumerate(candidates, start=1):
        if candidate.name in loaded_names:
            message = f"extensão duplicada ignorada: {candidate.name} ({candidate.source})"
            registry.warnings.append(message)
            registry.register_extension(
                ExtensionRecord(candidate.name, candidate.source, order, "ignored", message)
            )
            continue
        loaded_names.add(candidate.name)
        before_tools = set(registry.registrations)
        before_commands = set(registry.commands)
        before_handlers = {key: len(value) for key, value in registry._handlers.items()}
        record = ExtensionRecord(candidate.name, candidate.source, order, "loaded")
        registry.register_extension(record)
        try:
            extension = candidate.loader()
            module = _module_for(extension)
            settings = getattr(config, "extension_settings", {}).get(candidate.name, {})
            context = ExtensionContext(
                registry,
                config,
                session,
                name=candidate.name,
                source=candidate.source,
                settings=settings if isinstance(settings, dict) else {},
            )
            setup = getattr(module, "setup", None)
            if not callable(setup):
                raise TypeError("a extensão não define setup(pi) chamável")
            setup(context)
            record.tools = [name for name in registry.registrations if name not in before_tools]
            record.commands = [name for name in registry.commands if name not in before_commands]
        except Exception as exc:  # noqa: BLE001 — falha isolada por extensão
            for name in set(registry._tools) - before_tools:
                del registry._tools[name]
            for name in set(registry._commands) - before_commands:
                del registry._commands[name]
            for event in list(registry._handlers):
                prior = before_handlers.get(event, 0)
                del registry._handlers[event][prior:]
                if not registry._handlers[event]:
                    del registry._handlers[event]
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"[:400]
            registry.warnings.append(f"{candidate.name}: {record.error}")
        session.append_event(
            "extension_loaded",
            {
                "name": candidate.name,
                "source": candidate.source,
                "order": order,
                "status": record.status,
                "error": record.error,
                "tools": record.tools,
                "commands": record.commands,
            },
        )
    return registry.extensions


def _file_candidates(directory: Path, source: str) -> list[ExtensionCandidate]:
    if not directory.is_dir():
        return []
    candidates = []
    for path in sorted(directory.glob("*.py"), key=lambda item: item.name):
        if path.name.startswith("_"):
            continue
        name = path.stem
        candidates.append(
            ExtensionCandidate(
                name,
                source,
                lambda path=path, name=name, source=source: _load_file(path, name, source),
            )
        )
    return candidates


def _load_file(path: Path, name: str, source: str) -> ModuleType:
    safe_name = re.sub(r"\W+", "_", name)
    module_name = f"formiga_external_{source}_{safe_name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _module_for(value: object) -> object:
    if isinstance(value, ModuleType):
        return value
    # Entry-point pode apontar para o próprio setup callable.
    if callable(value):
        return type("LoadedExtension", (), {"setup": staticmethod(value)})
    return value
