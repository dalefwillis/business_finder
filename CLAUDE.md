# CLAUDE.md

Guidelines for working on this repository.

## Error Handling

- **Never silently swallow exceptions.** Code like `try: ... except: pass` is forbidden. Always log, re-raise, or collect errors for later display.
- **No silent data loss.** If data cannot be processed, emit a warning or accumulate failures for reporting. The user must always know when something went wrong.

## Scripts & Experiments

- Adhoc scripts are fine for quick discovery and exploration.
- Once an experiment yields useful insights, **save the script to the repo** for repeatability. Don't throw away working code.
- No need to `chmod +x` scripts—they will be run via `bash $FILE` or `python $FILE`.

## Python & Dependencies

- Always run Python through Poetry: `poetry run python ...` or `poetry run pytest`, etc.
- Keep `pyproject.toml` updated with any new dependencies. Install via `poetry add <package>` (not pip).
