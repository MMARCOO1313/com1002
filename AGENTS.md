# Repo Agent Guide

## Read First

Before any new task in this repo:

1. Read `memory.md`.
2. Run `git status --short --branch`.
3. Check whether the task touches backend, kiosk, frontend, or docs.
4. Update `memory.md` when a task is completed.

## Repo Conventions

- Remote: `origin = MMARCOO1313/com1002`
- Active branch prefix: `codex/`
- Keep the kiosk, backend API, and README in sync.
- If an endpoint changes, update both the caller and the docs in the same task.

## Verification Baseline

- Python: `python -m py_compile backend/main.py backend/session_manager.py backend/auto_queue.py backend/smart_control.py backend/alert_engine.py smartgate/kiosk.py smartcount/detect.py`
- Frontend: `npm run build` from `frontend/`

## Current Focus

- Complete the v2.0 GitHub deliverables.
- Maintain an accurate operation guide with diagrams.
- Preserve a running memory log in `memory.md`.
