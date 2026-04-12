# BridgeSpace V2 Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** finish the v2.0 GitHub deliverables by adding durable workflow docs, fixing the kiosk/backend session contract, and shipping an accurate operations guide.

**Architecture:** keep the current v2.0 system intact, but tighten the integration points that connect kiosk, backend, and documentation. The work is split into repo workflow infrastructure, contract repair, and operator-facing documentation so verification stays simple.

**Tech Stack:** Python, FastAPI, Tkinter, React, Vite, Markdown

---

### Task 1: Add durable workflow memory

**Files:**
- Create: `AGENTS.md`
- Create: `memory.md`

**Step 1: Write the initial docs**

- Add startup rules, canonical repo path, verification commands, and memory log expectations.

**Step 2: Verify the files are readable**

Run: `Get-Content AGENTS.md` and `Get-Content memory.md`
Expected: both files exist and describe the repo workflow clearly.

### Task 2: Fix kiosk and backend session contract drift

**Files:**
- Modify: `smartgate/kiosk.py`

**Step 1: Align session entry payload**

- Change kiosk session start calls to send `face_id` and optional `queue_id`.

**Step 2: Align session extension payload**

- Change kiosk extension calls to send `session_id`.

**Step 3: Preserve session metadata locally**

- Store `session_id`, `face_id`, and extension state in the kiosk session model so the timer and extend flow stay coherent.

**Step 4: Verify Python compilation**

Run: `python -m py_compile backend/main.py backend/session_manager.py backend/auto_queue.py backend/smart_control.py backend/alert_engine.py smartgate/kiosk.py smartcount/detect.py`
Expected: no syntax errors.

### Task 3: Add operation documentation with diagrams

**Files:**
- Create: `docs/operation-guide.md`
- Modify: `README.md`

**Step 1: Write the operator guide**

- Document startup, demo flow, subsystem roles, alerts, and recovery steps.
- Include architecture and flow diagrams.

**Step 2: Tighten README references**

- Link to the operation guide and correct any endpoint drift.

**Step 3: Verify frontend build**

Run: `npm run build`
Expected: Vite build completes successfully.

### Task 4: Update memory and prepare publication

**Files:**
- Modify: `memory.md`

**Step 1: Append completed work**

- Record every finished task with files changed and verification evidence.

**Step 2: Verify git status**

Run: `git status --short`
Expected: only intentional file changes remain.
