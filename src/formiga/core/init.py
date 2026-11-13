"""``formiga init``: create the home directory, config and database.

The generated config is a *layout* config: ``single`` with one ``base`` on machines that
cannot hold two models, ``dual`` when there is room. The deadline relaxation is the
point - the same profile is given a longer clock instead of a smaller promise.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from formiga.config import Settings, default_home
from formiga.core.doctor import suggested_layout, total_ram_gb
from formiga.i18n import t
from formiga.research.contract import permitted_profiles
from formiga.storage.db import ForeignSchema, connect, has_foreign_schema, migrate


@dataclass
class InitResult:
    """What ``init`` created or found."""

    home: Path
    layout: str
    ram_gb: float | None
    config_written: bool
    database_created: bool
    profiles: tuple[str, ...]
    backups: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "home": str(self.home),
            "layout": self.layout,
            "ram_gb": self.ram_gb,
            "config_written": self.config_written,
            "database_created": self.database_created,
            "profiles": list(self.profiles),
            "backups": list(self.backups),
        }


def render_config(*, layout: str, model: str = "base", endpoint: str = "http://127.0.0.1:8080",
                  language: str = "en") -> str:
    """Render the TOML skeleton written by ``init``."""
    if layout == "dual":
        body = """\
[layout]
name = "dual"

[layout.fast]
endpoint = "http://127.0.0.1:8080"
model = "small"
context = 4096
tool_call_format = "text"
supports_grammar = true
rung_ceiling = "bounded-edit"

[layout.strong]
endpoint = "http://127.0.0.1:8081"
model = "large"
context = 4096
tool_call_format = "none"
supports_grammar = true
rung_ceiling = "anchored-rewrite"
"""
    else:
        body = f"""\
[layout]
name = "{layout}"

[layout.fast]
endpoint = "{endpoint}"
model = "{model}"
context = 4096
tool_call_format = "text"
supports_grammar = true
rung_ceiling = "bounded-edit"
max_context_safe = 3072
"""
    return f"""\
# Formiga configuration. Edit by hand; `formiga doctor` explains each value.
language = "{language}"
output_language = "{language}"

{body}
[report]
profile = "medium"
citation_style = "apa"
max_quote_chars = 400
max_quote_chars_per_source = 900

[chat]
keep_turns = 4

[budget]
# Empty means "use the profile row" (PRD section 8.4).
"""


def init_home(
    *,
    home: Path | None = None,
    layout: str | None = None,
    language: str = "en",
    force: bool = False,
    ram_gb: float | None = None,
) -> InitResult:
    """Create the home directory, a config when absent, and migrate the database.

    A config written by an older format is moved aside rather than overwritten: the user
    may have spent time on it, and a backup costs nothing.
    """
    resolved = Path(home).expanduser() if home else default_home()
    resolved.mkdir(parents=True, exist_ok=True)
    detected = ram_gb if ram_gb is not None else total_ram_gb()
    chosen = layout or suggested_layout(detected)

    config_path = resolved / "config.toml"
    backups: list[Path] = []
    if config_path.exists() and _is_legacy_config(config_path):
        backups.append(_backup(config_path))
    config_written = False
    if not config_path.exists() or force:
        config_path.write_text(render_config(layout=chosen, language=language), encoding="utf-8")
        config_written = True

    db_path = resolved / "formiga.db"
    existed = db_path.exists()
    if _foreign_database(db_path):
        # Backup before the first open: connecting would let SQLite replay (and then
        # delete) another application's -wal file, losing it before we could preserve it.
        backups.append(_backup_database(db_path))
        existed = False
    connection = connect(db_path)
    try:
        try:
            migrate(connection, path=db_path)
        except ForeignSchema:
            # A shape we could not detect read-only; back it up and start clean.
            connection.close()
            backups.append(_backup_database(db_path))
            existed = False
            connection = connect(db_path)
            migrate(connection, path=db_path)
    finally:
        connection.close()

    from formiga.research.contract import validate_profile  # noqa: PLC0415 - avoids a cycle

    permitted = permitted_profiles(chosen, ram_gb=detected)
    validate_profile("medium", layout=chosen, ram_gb=detected, allow_heavy=True)

    return InitResult(
        home=resolved,
        layout=chosen,
        ram_gb=detected,
        config_written=config_written,
        database_created=not existed,
        profiles=permitted,
        backups=[str(path) for path in backups],
    )


def _foreign_database(path: Path) -> bool:
    """True when ``path`` exists and does not carry a Formiga manifest.

    The file is opened ``immutable``: SQLite then treats it as read-only and does not
    replay or delete a ``-wal`` beside it, which is what would happen on a normal open.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    uri = f"file:{path.resolve().as_posix()}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return True
    try:
        connection.row_factory = sqlite3.Row
        return has_foreign_schema(connection)
    except sqlite3.Error:
        return True
    finally:
        connection.close()


def _is_legacy_config(path: Path) -> bool:
    """True when the file uses a pre-v5 top-level layout."""
    import tomllib

    from formiga.config import LEGACY_TOP_LEVEL

    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return True
    return isinstance(data, dict) and bool(LEGACY_TOP_LEVEL & set(data))


def _backup_database(path: Path) -> Path:
    """Move a database aside together with its WAL and shared-memory siblings.

    Moving only the main file would leave a ``-wal`` beside the fresh database, and the
    next open would replay another application's writes into it.
    """
    target = _backup(path)
    for suffix in ("-wal", "-shm"):
        sibling = path.with_name(path.name + suffix)
        if sibling.exists():
            _backup(sibling)
    return target


def _backup(path: Path) -> Path:
    """Move ``path`` aside, never deleting it, and return the new location."""
    import shutil

    suffix = 1
    target = path.with_name(f"{path.name}.legacy")
    while target.exists():
        suffix += 1
        target = path.with_name(f"{path.name}.legacy{suffix}")
    shutil.move(str(path), target)
    return target


def init_messages(result: InitResult, *, locale: str = "en") -> list[str]:
    messages = [
        t("init.created" if result.config_written else "init.exists", locale=locale,
          path=str(result.home)),
        t("init.layout", locale=locale, layout=result.layout,
          ram=result.ram_gb if result.ram_gb is not None else "?"),
        t("init.profile_limit", locale=locale, profiles=", ".join(result.profiles)),
    ]
    if result.backups:
        messages.append(
            t("init.backup", locale=locale, paths=", ".join(result.backups))
        )
    return messages


def settings_from(result: InitResult) -> Settings:
    """Load the settings the just-initialised home would produce."""
    from formiga.config import load_settings  # noqa: PLC0415 - avoids a cycle

    return load_settings(home=result.home)


__all__ = [
    "InitResult",
    "init_home",
    "init_messages",
    "render_config",
    "settings_from",
]
