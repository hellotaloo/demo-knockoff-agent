# Taloo - Voice Agent Architecture & Features

## Conversation Flow

- Multi-agent architecture with smooth handoffs (Greeting → Screening → Open Questions → Scheduling)
- Configurable consent recording before the interview starts (optional)
- Identity verification for known candidates from CRM
- Proxy detection — recognizes when someone else is calling on behalf of the candidate
- Known candidate data is pre-loaded from CRM to skip already-answered questions, making the call shorter
- Alternative vacancy flow when a candidate fails a knockout question
- Interview scheduling with real-time timeslot lookup

## Voice & Language

- Natural Flemish Dutch (not formal ABN, not dialect)
- Automatic language switching — if the candidate switches to another languager. TTS model (ElevenLabs Flash v2.5) supports 32 languages including Dutch, English, French, Spanish, German, Arabic, Turkish, Polish, and more
- Consistent voice and accent throughout the entire conversation
- Human-like recruiter tone — warm, enthusiastic, professional
- Short responses (max 2-3 sentences per turn) to feel like a real phone call
- Never repeats the same sentence — varies word choice to avoid sounding robotic
- No exclamation marks — uses periods and question marks only for natural speech
- Times spoken in natural language ("10 uur", "half 3") instead of "10:00"

## Turn Detection & Silence Handling

- Semantic turn detection disabled for yes/no questions to avoid false triggers
- VAD-only mode for open questions with 2-second endpointing delay — gives candidates time to think
- Two-step silence fallback: first a gentle "are you there?", then gracefully ends the call
- Silence suppression during agent intro sequences to prevent false silence triggers
- Silence counter resets when the user speaks again

## Audio Experience

- Office ambience background sound for a professional atmosphere
- Keyboard typing sounds during processing to signal "I'm noting that down"
- Noise cancellation (BVC for browser, BVC Telephony for phone calls)
- Thinking audio only starts after greeting, not during the initial hello

## Knockout Questions

- Double confirmation on negative answers — repeats back the specific answer before marking as failed ("Dus je hebt geen rijbewijs, klopt dat?")
- Context-aware clarification — if a candidate asks about a question, the agent can explain using background context without reading it verbatim
- Notes for recruiter — candidate questions the agent can't answer are saved for follow-up
- Smooth transitions between questions with natural acknowledgment of previous answers
- "Last question" indicator when one question remains

## Open Questions

- Candidate's previous audio is cleared between questions to avoid bleed-over
- Single answer per question — no follow-up interrogation
- Answer summaries are stored for the recruiter

## Scheduling

- Proposes 3 timeslots from the first available weekdays based on real-time availability
- If none fit, asks the candidate which days work better and looks up additional slots
- If no match after 2 failed lookups, automatically escalates to recruiter with the candidate's preference
- Candidate can also indicate they can't come to the office physically — agent escalates with that context
- Confirms the chosen timeslot with full details (day, date, time, office location, address)
- Smart follow-up: "You'll get a WhatsApp confirmation" or "...and a reminder" depending on how far out the appointment is
- Skips scheduling entirely if the candidate already has an existing booking in CRM
- Times always spoken naturally ("10 uur", "half 3"), never "10:00" or "14:30"
- Max 3-4 timeslots at once to avoid overwhelming the candidate over the phone

## Candidate Context

- Known candidates from CRM get a shorter, more personal call — already-answered knockout questions are skipped
- Identity verification for known candidates ("We see you're already in our system. Can you confirm you're Mark?")
- Candidate name is used throughout the conversation for a personal touch
- Pre-loaded CRM data (known answers, existing bookings) reduces call duration
- All results are stored per candidate: knockout answers, open question summaries, consent status, chosen timeslot, recruiter notes
- Voicemail detection — if the candidate doesn't pick up and an answering machine is detected, Anna leaves a short callback message and hangs up

## Usage Tracking & Cost

- Per-session usage metrics collected automatically (LLM tokens, TTS characters, STT audio duration)
- Cost breakdown in USD calculated per session (LLM, TTS, STT separately + total)
- Usage logs saved as JSON files on session shutdown
- Cost rates: GPT-4.1-mini ($0.40/$1.60 per M tokens), ElevenLabs Flash v2.5 ($11.25/M chars), Deepgram Nova-3 ($0.462/hr)
- Typical cost per call: ~$0.04 for a 2-minute call, ~$0.10-0.15 for a full 5-minute call

## Edge Case Handling

- Voicemail detection — detects answering machines and leaves a brief callback message
- Trolling detection — after 2+ irrelevant/nonsensical answers, gracefully ends the conversation
- Escalation to human recruiter on request (configurable on/off)
- The agent never invents answers — unknown questions are noted for the recruiter
- Never says "werken bij Its You" — always refers to the role, not the agency as employer
