# Virtual Environment Rule

All local development work MUST use the project's Python virtual environment.

## Requirements

1. **Always use `.venv/`** — the virtual environment lives at the project root
2. **All Python commands** must use `.venv/bin/python3` or `.venv/bin/<tool>` (e.g. `.venv/bin/pytest`)
3. **All pip installs** must target the venv: `.venv/bin/pip install ...`
4. **Never use system Python** for project work — no bare `python3` or `pip`
5. **On startup**, verify the venv exists and has all dependencies from `requirements.txt`

## Setup (if venv is missing)

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## System CLI tools

Tools that are not Python packages (e.g. `doctl`, `gh`, `rsync`, `ssh`)
are installed via Homebrew and are available system-wide. These do NOT
go in the virtual environment.

Required system tools:
- `gh` — GitHub CLI (PRs, issues)
- `doctl` — DigitalOcean CLI (droplet power on/off)
- `rsync` — file sync from droplet
- `ssh` — remote access to droplet
