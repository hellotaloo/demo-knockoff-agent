# Prescreening Voice Agent — Backend Integration Brief

What it does
Autonomous voice agent that pre-screens job candidates over the phone. Handles greeting, knockout questions (yes/no), open questions, and interview scheduling. Supports 32 languages with auto-detection. Runs as a LiveKit agent (Docker container).

How to dispatch a call
Create a LiveKit agent dispatch with a SessionInput JSON payload as room metadata:


from livekit import api

lkapi = api.LiveKitAPI()

# 1. Create dispatch with session config as metadata
await lkapi.agent_dispatch.create_dispatch(
    api.CreateAgentDispatchRequest(
        agent_name="elevenlabs-agent",
        room=room_name,
        metadata=json.dumps(session_input),  # ← JSON below
    )
)

# 2. Dial the candidate into the room via SIP
await lkapi.sip.create_sip_participant(
    api.CreateSIPParticipantRequest(
        room_name=room_name,
        sip_trunk_id="ST_xxx",
        sip_call_to="+32...",
        participant_identity="phone_user",
        wait_until_answered=True,
    )
)
Input: SessionInput (room metadata JSON)

{
  "call_id": "abc-123",
  "candidate_name": "Mark Verbeke",
  "candidate_known": false,
  "candidate_record": {
    "known_answers": {"work_permit": "ja"},
    "existing_booking_date": "dinsdag 4 maart om 10 uur"
  },
  "job_title": "Bakkerij Medewerker",
  "office_location": "Antwerpen Centrum",
  "office_address": "Mechelsesteenweg nummer 27",
  "knockout_questions": [
    {"id": "q1", "text": "Mag je wettelijk werken in Belgie?", "internal_id": "crm_field_1", "data_key": "work_permit", "context": ""},
    {"id": "q2", "text": "Heb je ervaring?", "internal_id": "crm_field_2", "data_key": "experience", "context": ""}
  ],
  "open_questions": [
    {"id": "oq1", "text": "Waarom wil je hier werken?", "internal_id": "crm_field_3", "description": "Motivatie"}
  ],
  "allow_escalation": true,
  "require_consent": true
}
Field	Required	Notes
call_id	yes	Your unique ID to correlate results back
candidate_name	no	Used in greeting. Empty = generic greeting
candidate_known	no	true = returning candidate, skips known answers via candidate_record
candidate_record	no	Pre-known answers (skips those knockout questions). existing_booking_date skips scheduling
job_title	yes	Used throughout the conversation
office_location / office_address	no	For scheduling confirmation message
knockout_questions	yes	Yes/no questions. data_key links to candidate_record.known_answers
open_questions	yes	Free-form questions, answered after knockout
internal_id	no	Passthrough field — returned as-is in results for your CRM mapping
allow_escalation	no	Default true. Gives candidate option to talk to human recruiter
require_consent	no	Default true. Asks recording consent in greeting
Output: CandidateData (session results)
Returned by _on_session_complete() callback at session end. Currently logged — needs a webhook or message queue push to your backend.


{
  "call_id": "abc-123",
  "status": "completed",
  "consent_given": true,
  "voicemail_detected": false,
  "passed_knockout": true,
  "interested_in_alternatives": false,
  "knockout_answers": [
    {
      "question_id": "q1",
      "internal_id": "crm_field_1",
      "question_text": "Mag je wettelijk werken in Belgie?",
      "result": "pass",
      "raw_answer": "ja, ik heb een werkvergunning",
      "candidate_note": ""
    }
  ],
  "open_answers": [
    {
      "question_id": "oq1",
      "internal_id": "crm_field_3",
      "question_text": "Waarom wil je hier werken?",
      "answer_summary": "Candidate is passionate about baking...",
      "candidate_note": ""
    }
  ],
  "chosen_timeslot": "dinsdag 4 maart om 10 uur",
  "scheduling_preference": null
}
Possible status values:

Status	Meaning
completed	Full flow done, timeslot chosen or preference recorded
voicemail	Hit voicemail, left a message
not_interested	Candidate declined or failed knockout + not interested in alternatives
knockout_failed	Failed a knockout question but interested in other vacancies
escalated	Candidate requested human recruiter
unclear	Couldn't get a clear answer after retries
irrelevant	Too many off-topic answers (3 max)
incomplete	Session ended unexpectedly (silence timeout, disconnect)
Knockout result values: pass, fail, unclear, irrelevant, recruiter_requested

TODO for integration
Results callback — agent.py:213-217 has a TODO. Add your webhook POST or queue push there
Environment variables — needs LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY, ELEVEN_API_KEY
Deployment — Dockerfile is ready. Build & push, then lk agent create to register with LiveKit Cloud
Want me to adjust the tone, add/remove sections, or implement the results callback?