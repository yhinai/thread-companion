# Implementation contributions

This repository captures the Thread implementation developed locally for the October 11, 2026 MongoDB Harness Engineering & Model Wrangling hackathon. Its initial Git commit is a snapshot after local development, not a historical record of every edit. Private conversation records and runtime credentials are excluded.

## Thread code

- `companion/engine.py`, `codex.py`, `process.py`, and `gitops.py`: supervised Codex execution, cancellable subprocesses, isolated alternatives, fixed checks, fresh review, recoverable promotion, and persisted runs.
- `companion/memory.py` and `store.py`: versioned note projections, typed context selection, linked provenance, source-dependent invalidation, SQLite development storage, and Atlas persistence.
- `companion/proof.py`, `grading.py`, and `evaluation.py`: changed-decision fixture, fixed external acceptance criteria, and randomized fresh-session comparisons across three context conditions.
- `companion/server.py` and `plugin/`: authenticated loopback API and an Obsidian command/activity/evidence interface.
- `companion/doctor.py` and `scripts/`: setup diagnostics, private Atlas configuration helper, fixture preparation, and plugin installation.
- `tests/`: deterministic orchestration, memory lifecycle, cancellation, promotion integrity, proof, and HTTP checks. Test doubles are explicitly labeled and do not establish live model performance.

## Existing tools and dependencies

Thread uses the existing Codex CLI and model service, Obsidian's plugin API, Git worktrees, Python's standard library, and MongoDB Atlas through PyMongo. These platforms are not original Thread contributions. Product research informed the design; the implementation does not incorporate source code from the referenced memory projects.

## Evidence and unfinished work

The local suite passes all 24 tests, including live HTTP integration. Atlas ping/read/write and the real Codex learning/check/review loop passed in the receiving session. Learning improved the fixed acceptance score from 11/16 to 16/16. All three transfer conditions passed 6/6 tasks, so incremental procedural benefit was not demonstrated. A separately started coordinator retrieved this evidence and completed an authenticated Brief with a linked vault note.

Obsidian is installed and the plugin is configured, but native application inspection timed out, leaving visual verification incomplete. Public availability does not imply that a submission or demo video has been completed.
