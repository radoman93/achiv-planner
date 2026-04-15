# Claude Code Session Templates

Copy-paste these prompts at the start of each Claude Code session.

---

## 🚀 Standard Session Opener

Use this at the start of every session:

```
Read CLAUDE.md for project context.
Read docs/progress.md to see where we are.
Read docs/phase-X-tasks.md for the current phase tasks.

Continue from TASK X.Y — [Task Name].
[Add any notes from last session here if relevant.]
```

---

## 🆕 Starting a New Phase

```
Read CLAUDE.md for project context.
Read docs/progress.md — Phase 1 is now complete.
Read docs/phase-Y-tasks.md — we are starting Phase Y.

Begin with TASK 2.1. Verify acceptance criteria before 
moving to the next task. Update docs/progress.md after 
each completed task.

Do all tasks.
```

---

## ✅ Moving Between Tasks (Same Session)

```
TASK X.Y acceptance criteria pass. Mark it complete in 
docs/progress.md and move to TASK X.Z — [Task Name].
Read docs/phase-X-tasks.md for the full spec.
```

---

## 🔧 Fixing a Specific Task

```
Read CLAUDE.md for project context.
Read docs/phase-X-tasks.md.

TASK X.Y has an issue: [describe the problem].
The acceptance criteria failing are: [list them].
Fix only TASK X.Y — do not modify other tasks.
```

---

## 🔄 After Claude Code Gets Confused

```
Stop. 
Read CLAUDE.md again.
Read docs/progress.md.
Read docs/phase-X-tasks.md.

We are working on TASK X.Y only. 
[Restate what you need it to do.]
```

---

## 📋 Acceptance Criteria Verification Prompt

After completing any task:

```
Before moving forward, verify ALL acceptance criteria 
for TASK X.Y from docs/phase-X-tasks.md.

Run whatever tests, scripts, or checks are needed 
to confirm each criterion passes. Report results 
for each criterion as PASS or FAIL with evidence.
Only proceed if all criteria pass.
```

---

## Phase Reference

| Phase | Focus | Task File |
|---|---|---|
| 0 | Infrastructure Bootstrap | docs/phase-0-tasks.md |
| 1 | Backend Foundation | docs/phase-1-tasks.md |
| 2 | Scraping Pipeline | docs/phase-2-tasks.md |
| 3 | Routing Engine | docs/phase-3-tasks.md |
| 4 | API Layer | docs/phase-4-tasks.md |
| 5 | Frontend | docs/phase-5-tasks.md |
| 6 | Background Jobs & Sync | docs/phase-6-tasks.md |
| 7 | Hardening & Deployment | docs/phase-7-tasks.md |
