Taloo Prescreening Agent — Implementation Plan
Context
The current taloo-prescreening/agent.py is a bare skeleton with a single Assistant agent and no workflow logic. We need to implement the full prescreening flowchart: greeting → knockout questions → open questions → scheduling (or alternative path on failure). The existing prescreening-handoff/agent.py already proves the agent handoff pattern works with ElevenLabs TTS — we'll reuse that approach and enhance it with TaskGroups for structured question flows.

Architecture
Agent handoffs for major phase transitions (greeting → screening → scheduling)
Individual AgentTask calls in a loop for knockout questions (need early exit on fail)
TaskGroup for open questions (all questions always asked, supports regression)
Separate SchedulingAgent with silent handoff (user doesn't notice)
CandidateData dataclass as shared session state via userdata
File Structure

taloo-prescreening/
├── agent.py                    # Entrypoint (modify existing)
├── models.py                   # CandidateData + result dataclasses (new)
├── prompts.py                  # All prompt strings centralized (new)
├── agents/
│   ├── __init__.py
│   ├── greeting.py             # Waits for user, introduces Anna
│   ├── screening.py            # Runs knockout questions in a loop
│   ├── open_questions.py       # Runs open questions via TaskGroup
│   ├── scheduling.py           # Interview slot booking
│   └── alternative.py          # Path for failed knockout
└── tasks/
    ├── __init__.py
    ├── knockout.py             # Reusable yes/no question task
    └── open_question.py        # Reusable open-ended question task
Steps (incremental, each testable)

### Step 1: Data model + project skeleton
Create models.py with CandidateData, KnockoutResult, OpenQuestionResult dataclasses
Create prompts.py with prompt constants
Create empty agents/ and tasks/ directories with __init__.py
Update agent.py to use AgentSession[CandidateData] with userdata=CandidateData()
Test: Agent still starts and works as before

### Step 2: Greeting Agent
Create agents/greeting.py — waits for user to speak, introduces Anna, asks if they have time
Two function tools: candidate_ready (→ handoff to screening) and candidate_not_available (→ goodbye)
Update agent.py to start with GreetingAgent instead of Assistant
Test: Connect, speak first, agent introduces itself. Say "ja" → logs show handoff attempt. Say "nee" → polite goodbye.

### Step 3: Knockout question task
Create tasks/knockout.py — KnockoutTask(AgentTask[KnockoutResult]) with on_enter() that asks the question
Three function tools: mark_pass, mark_fail, mark_irrelevant
Test: Create a temporary test agent that runs a single KnockoutTask directly. Verify pass/fail/irrelevant results.

### Step 4: Screening Agent with knockout loop
Create agents/screening.py — runs knockout questions sequentially (NOT TaskGroup — we need early exit)
Loop through questions: on PASS → next question, on FAIL → handoff to alternative, on IRRELEVANT → end call
All passed → handoff to open questions agent
Test: Wire greeting → screening. Answer all "ja" → proceeds. Answer "nee" → alternative path. Gibberish → end call.

### Step 5: Open question task + Open Questions Agent
Create tasks/open_question.py — OpenQuestionTask(AgentTask[OpenQuestionResult]) with record_answer tool
Create agents/open_questions.py — uses TaskGroup for 3 open questions (all always asked, supports regression)
After all answered → handoff to scheduling
Test: Skip directly to open questions agent. All 3 questions asked, answers acknowledged naturally.

### Step 6: Alternative Agent
Create agents/alternative.py — asks if interested in other jobs
If yes → runs 3 fixed open questions → goodbye
If no → goodbye
Test: Skip directly to alternative agent. Both paths work.

### Step 7: Scheduling Agent
Create agents/scheduling.py — silent handoff, presents timeslots, confirms booking
Function tools: get_available_timeslots, confirm_timeslot, no_suitable_slot
Pattern from prescreening-handoff/agent.py:84-101 — uses on_enter() with session.say() + generate_reply()
Test: Skip directly to scheduling agent. Pick a slot → confirmation. No slot fits → records preference.

### Step 8: Wire everything + end-to-end testing
Connect all agents in agent.py
Test the full happy path and all branching scenarios
Test matrix:
Happy path: greeting → 3 knockout pass → 3 open questions → schedule → goodbye
Knockout fail (genuine): greeting → q1 pass → q2 fail → alternative interested → 3 alt questions → goodbye
Knockout fail (not interested): greeting → q1 fail → alternative not interested → goodbye
Irrelevant/trolling: greeting → q1 gibberish → polite end
No time: greeting → no time → goodbye
Key references to reuse
prescreening-handoff/agent.py:84-101 — SchedulingAgent pattern with on_enter(), session.interrupt(), session.say(), generate_reply()
prescreening-handoff/agent.py:49-61 — ScreeningAgent handoff pattern with function_tool + session.update_agent()
prescreening-handoff/agent.py:128-137 — OtherFunctionsAgent pattern for alternative path
TaskGroup import: from livekit.agents.beta.workflows import TaskGroup
AgentTask import: from livekit.agents import AgentTask
Pipeline fallback (if realtime model causes issues)
Only agent.py session config changes — all agents/tasks stay identical:


# Replace realtime with pipeline:
stt="deepgram/nova-3:multi", llm="openai/gpt-4.1-mini",
vad=silero.VAD.load(), turn_detection=MultilingualModel()
Verification
After each step: uv run agent.py dev → connect via LiveKit Playground → test the specific scenario for that step.

Stayed in plan mode