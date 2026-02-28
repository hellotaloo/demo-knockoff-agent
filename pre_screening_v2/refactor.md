# Production Readiness Review

## Context

The prescreening agent is feature-complete and tested. Before deploying to production, we need to review the codebase for: duplicated patterns that create maintenance risk, over-engineering that could cause failures, inconsistencies, and missing production plumbing.

**Architecture:** This code lives directly in the backend (same codebase, same database). The backend creates vacancies with questions, then dispatches the voice agent via LiveKit when a candidate leaves their number. The agent shares DB access with the backend — no separate API needed for results.

---

## TIER 1: Must-Fix Before Production

### ~~1.1 Remove `DEBUG_TODAY` from scheduling.py~~ ✅ DONE

- Removed `DEBUG_TODAY`, `_build_slots()` now uses `date.today()`
- Slots rebuilt per session in `on_enter()` (no more stale module-level data)
- Simplified `_build_slots()`: returns flat list of 3 slots (removed `by_day` dict)
- Removed `lookup_slots_for_days` tool and `_failed_lookups` counter (over-engineered)
- Simplified prompt: if none of the 3 slots fit → `schedule_with_recruiter` directly
- Tests updated and passing

### ~~1.2 Isolate private SDK access (`session._opts`)~~ ✅ DONE

- Created `_set_user_away_timeout()` helper in `agents/open_questions.py`
- Both usages now go through the helper with try/except
- One place to update when SDK adds a public API

### ~~1.3 Clean entry point: dispatch function + SessionInput serialization~~ ✅ DONE

- Added `call_id` to `SessionInput`, `internal_id` to questions and answers
- Added `SessionInput.to_dict()` and `SessionInput.from_dict()` for JSON serialization
- Added `CandidateData.to_dict()` with auto-resolved `status` and `internal_id` lookup
- Entrypoint now parses `ctx.job.metadata` as JSON, falls back to dev input
- Extracted hardcoded config into `_dev_session_input()`

### ~~1.4 Save session results~~ ✅ DONE

- Added `_on_session_complete` shutdown callback in `agent.py`
- Calls `session.userdata.to_dict()` and logs status
- TODO placeholder for backend event trigger (DB save, review agent, etc.)

---

## TIER 2: Consolidate Duplicated Patterns

### ~~2.1 Create `BaseAgent` with shared tools~~ ✅ DONE

- Created `agents/base.py` with `BaseAgent` containing `end_conversation_irrelevant` and `escalate_to_recruiter`
- All 6 agents now inherit from `BaseAgent` instead of `Agent`
- RecruiterAgent passes `allow_escalation=False` (no-op escalation)
- Fixed SchedulingAgent inconsistency (`self.session.userdata.input.allow_escalation` → `self._allow_escalation` via base class)
- Removed ~120 lines of duplicated code
- All tests passing

### ~~2.2 Extract shared string constants~~ ✅ DONE

- Defined `MSG_IRRELEVANT_SHUTDOWN` and `MSG_RECRUITER_HANDOFF` in `agents/base.py`
- `base.py`, `screening.py`, `open_questions.py`, `alternative.py` all use the constants
- All tests passing

### ~~2.3 Consolidate TaskGroup pattern~~ ✅ DONE

- Added `_run_open_questions()` method to `BaseAgent` in `agents/base.py`
- Takes list of `(id, text, description, response_message)` tuples, returns `bool` (recruiter requested)
- Both `OpenQuestionsAgent` and `AlternativeAgent` now call `self._run_open_questions()`
- Removed ~25 lines of duplicated TaskGroup/results logic
- All tests passing

### ~~2.4 Move ReadyCheckTask to `tasks/`~~ ✅ DONE

- Moved `ReadyCheckTask` from `agents/open_questions.py` to `tasks/ready_check.py`
- `open_questions.py` now imports from `tasks.ready_check`
- Cleaned up unused imports (`AgentTask`, `RunContext`, `function_tool`)
- All tests passing

---

## TIER 3: Minor Cleanup

### ~~3.1 Unify `mark_irrelevant` across tasks~~ ✅ DONE

- Added `check_irrelevant(userdata, suffix)` helper in `models.py`
- All 3 tasks + `BaseAgent.end_conversation_irrelevant` now use the helper
- Counting logic defined once, each caller handles its own completion

### ~~3.2 Remove redundant `llm=` specifications~~ ✅ DONE

- Removed `llm="openai/gpt-4.1-mini"` from screening, open_questions, alternative, scheduling
- Session default in `agent.py` is the single source of truth

### ~~3.3 Fix stale comment in alternative.py~~ ✅ DONE (already removed in earlier refactoring)

---

## Items NOT Worth Changing

- **Transition text complexity in ScreeningAgent** — produces natural conversation, complexity is in orchestration code (correct place)
- **ReadyCheckTask scope** — only needed before open questions, not worth consolidating with other yes/no patterns
- **Silence suppression pattern** — 3 lines each, very obvious, context manager adds indirection without benefit

---

## TIER 4: Future Features

### 4.1 Language-aware hardcoded strings

All `session.say()` strings (irrelevant shutdown, recruiter handoff, scheduling confirmations, etc.) are hardcoded in Dutch. If the user switches to English/French/Spanish mid-conversation, the LLM adapts but these hardcoded strings still play in Dutch.

**Fix:** Either pass these messages through the LLM for translation before saying them, or maintain a small translation map keyed by detected language.

---

## Verification

```bash
# Run full test suite after each tier
uv run pytest tests/ -s -v

# Manual test: run agent end-to-end via playground
# Verify: greeting → screening → open questions → scheduling flow unchanged
# Verify: escalation, irrelevant handling, silence handling all work
```
