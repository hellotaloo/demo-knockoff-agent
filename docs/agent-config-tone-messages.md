# Pre-screening WhatsApp Agent Configuration System

## Goal
Allow recruiters to configure the agent's **tone/behavior** and **messages** without touching code.

---

## Current State

**Existing `agents.configs` table:**
```
id                      uuid (PK)
pre_screening_id        uuid (FK)
max_unrelated_answers   int (default 2)      ← Already in UI
schedule_days_ahead     int (default 3)      ← Already in UI
schedule_start_offset   int (default 1)      ← Already in UI
planning_mode           varchar ('funnel')
intro_message           text (nullable)      ← Exists but not used
success_message         text (nullable)      ← Exists but not used
created_at, updated_at
```

**Current agent tone (hardcoded in prompts):**
- Casual/excited with emojis (👋 🚀 ✓)
- Short responses: "Top!", "Check!", "Mooi!"
- Flemish Dutch

---

## What To Add

### 1. Tone/Behavior Setting

New column: `tone` (enum)

| Value | Description | Example Responses |
|-------|-------------|-------------------|
| `excited` | Current default - energetic, emojis | "Super leuk! 🚀", "Top! ✓" |
| `relaxed` | Casual but calmer, minimal emojis | "Fijn!", "Oke, duidelijk." |
| `formal` | Professional, no emojis, polite | "Dank u.", "Uitstekend." |
| `neutral` | Balanced, straightforward | "Goed.", "Begrepen." |

**Implementation:** Inject tone instructions into prompts:
```python
TONE_INSTRUCTIONS = {
    "excited": "Schrijf enthousiast met emojis. Gebruik woorden als 'Super!', 'Top!', 'Mooi!'",
    "relaxed": "Schrijf vriendelijk maar rustig. Minimale emojis. Woorden als 'Fijn', 'Oke', 'Prima'.",
    "formal": "Schrijf professioneel en beleefd. Geen emojis. Gebruik 'u' vorm. Woorden als 'Uitstekend', 'Dank u'.",
    "neutral": "Schrijf direct en zakelijk. Geen emojis. Kort en bondig."
}
```

### 2. Custom Messages

Expand existing `intro_message` and `success_message` usage + add more:

| Column | Purpose | Variables Available |
|--------|---------|---------------------|
| `intro_message` | Custom welcome (replaces HELLO_PROMPT output) | `{candidate_name}`, `{vacancy_title}`, `{company_name}` |
| `success_message` | After scheduling confirmed | `{candidate_name}`, `{scheduled_time}`, `{recruiter_name}` |
| `knockout_fail_message` | When candidate doesn't qualify | `{candidate_name}`, `{requirement}` |
| `goodbye_message` | Final goodbye (no interest in alternatives) | `{candidate_name}` |

**Behavior:** Custom messages are used **exactly as written** (variables substituted). No LLM processing.
If null, the default LLM-generated message (with tone applied) is used.

---

## Database Migration

```sql
ALTER TABLE agents.configs
  ADD COLUMN tone VARCHAR(20) DEFAULT 'excited'
    CHECK (tone IN ('excited', 'relaxed', 'formal', 'neutral')),
  ADD COLUMN knockout_fail_message TEXT,
  ADD COLUMN goodbye_message TEXT;
```

---

## UI Addition to Existing Page

Add a new section to the existing pre-screening settings page:

```
┌─────────────────────────────────────────────────────┐
│  Gedrag & Toon                                      │
│  Configureer de communicatiestijl van de agent      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Toon                                               │
│  ○ Enthousiast  - "Super leuk! 🚀 Top!"            │
│  ● Relaxed      - "Fijn! Oke, duidelijk."          │
│  ○ Formeel      - "Dank u. Uitstekend."            │
│  ○ Neutraal     - "Goed. Begrepen."                │
│                                                     │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  Berichten                                          │
│  Pas standaard berichten aan (optioneel)            │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Welkomstbericht                                    │
│  [x] Gebruik standaard  [ ] Aangepast              │
│  Preview: "Hey {candidate_name}! 👋 Super leuk..." │
│                                                     │
│  Bevestigingsbericht (na planning)                 │
│  [x] Gebruik standaard  [ ] Aangepast              │
│                                                     │
│  Bericht bij niet-kwalificatie                     │
│  [x] Gebruik standaard  [ ] Aangepast              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1: Database
- Add `tone`, `knockout_fail_message`, `goodbye_message` columns to `agents.configs`

### Phase 2: Agent Integration
- Create `TONE_INSTRUCTIONS` dict with tone-specific prompt additions
- Modify prompt templates to inject tone instructions
- Use custom messages from config when not null

### Phase 3: API
- Update existing config endpoints to handle new fields
- Add validation for tone enum

### Phase 4: Frontend
- Add "Gedrag & Toon" section to existing settings page
- Add "Berichten" section with toggles + text areas

---

## Files to Modify

| File | Changes |
|------|---------|
| `pre_screening_whatsapp_agent/agent.py` | Add TONE_INSTRUCTIONS, inject into prompts |
| `src/models/` | Update config Pydantic models |
| `src/repositories/` | Update config repo if needed |
| `src/routers/` | Update config endpoints |

---

## What Stays Hardcoded
- Forbidden words list (safety)
- LLM models (technical)
- Phase flow logic (core business)
- Recruiter name (injected dynamically)
