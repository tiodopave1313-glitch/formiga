# Uninstall

Formiga stores everything on the local machine. Uninstalling is removing the package and,
optionally, the data. Nothing is uploaded, so there is no server-side account to delete.

## 1. Where the data lives

| Path | Contents | Safe to delete? |
|---|---|---|
| `~/.formiga/config.toml` | Your configuration | Yes, but you lose your settings |
| `~/.formiga/formiga.db` | Runs, sources, notes, claims, citations, LLM cache | Yes, but you lose all research history |
| `~/.formiga/formiga.db-wal`, `formiga.db-shm` | SQLite write-ahead log and shared memory | Yes, together with the database |
| `~/.formiga/cache/` | Fetched page text (30-day retention by default) | Yes |
| `~/.formiga/runs/` | Per-run working directories and lock files | Yes |
| `~/.formiga/logs/` | `events.jsonl` (rotated at 10 MB, last 3 kept) | Yes |
| `~/.formiga/skills/` | User-installed skills (plain text) | Yes, unless you wrote them |
| `~/.formiga/memory.md` | The memory file; user-editable | **Check before deleting** - it is your notes |
| `~/formiga/reports/` | Rendered reports (`.md` and `.json`) | Yes, but they are the point of the tool |
| `~/.formiga/*.legacy*` | State moved aside by a v5 upgrade | Yes, once you are sure you do not want it |

If you set `XDG_DATA_HOME`, the application home is `$XDG_DATA_HOME/formiga` instead of
`~/.formiga`. If you set `FORMIGA_HOME`, it is whatever you set. If you set
`FORMIGA_REPORTS_DIR`, reports live there. Check first:

```bash
printf 'home=%s\nreports=%s\n' "${FORMIGA_HOME:-${XDG_DATA_HOME:-$HOME}/.formiga}" \
  "${FORMIGA_REPORTS_DIR:-$HOME/formiga/reports}"
```

## 2. Remove the package

With `uv` (the documented install path):

```bash
uv tool uninstall formiga-cli
```

Or, in a checkout, delete the virtual environment you created:

```bash
rm -rf .venv
```

## 3. Remove the data

Preview the exact paths before removing anything:

```bash
ls -la ~/.formiga ~/formiga/reports
```

Then remove the stores you no longer want:

```bash
rm -rf ~/.formiga            # config, database, cache, logs, skills, memory
rm -rf ~/formiga/reports     # rendered reports
```

Each is independent: keeping reports while deleting the database is a valid choice, and the
reports remain readable Markdown.

## 4. Model files

Formiga does not download or manage GGUF weights; `llama-server` does, and the weights live
wherever you put them. Remove them with whatever tool fetched them. `formiga bench` and
`formiga serve` only read the paths your configuration names.

## 5. Nothing else

- No telemetry, no accounts, no cloud API keys.
- No files outside the paths above and the Python environment.
- No system service, no cron entry, no shell profile change: `formiga init` writes only inside
  the application home.
