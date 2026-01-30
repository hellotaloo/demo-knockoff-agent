# Pre-Screening API - Frontend Integration

## Key Change: Session Auto-Restore

`GET /vacancies/{vacancy_id}/pre-screening` now automatically creates an interview session for AI editing. No separate call needed.

---

## Get Pre-Screening

```
GET /vacancies/{vacancy_id}/pre-screening
```

**Response:**
```json
{
  "id": "8db32ea5-...",
  "vacancy_id": "5779f190-...",
  "intro": "Hallo! Leuk dat je solliciteert.",
  "knockout_questions": [...],
  "qualification_questions": [...],
  "knockout_failed_action": "...",
  "final_action": "...",
  "status": "active",
  "created_at": "...",
  "updated_at": "...",
  "session_id": "5779f190-...",
  "interview": {
    "intro": "...",
    "knockout_questions": [{ "id": "ko_1", "question": "..." }],
    "qualification_questions": [
      { 
        "id": "qual_1", 
        "question": "...", 
        "ideal_answer": "What we want to hear in a good response..." 
      }
    ],
    "knockout_failed_action": "...",
    "final_action": "...",
    "approved_ids": ["ko_1", "qual_1"]
  }
}
```

**New fields:**
| Field | Description |
|-------|-------------|
| `session_id` | Use for `/interview/feedback` calls (equals `vacancy_id`) |
| `interview` | Agent-compatible format for the chat UI |

---

## Qualification Question Structure

Each qualification question now includes an `ideal_answer` field:

```typescript
interface QualificationQuestion {
  id: string;           // "qual_1", "qual_2", etc.
  question: string;     // The question asked to the candidate
  ideal_answer: string; // Guidance for AI scoring - what makes a good answer
  is_modified?: boolean;
}
```

### What is `ideal_answer`?

The `ideal_answer` field tells the downstream AI agent what the recruiter wants to hear when scoring candidate responses. It's **not** shown to candidates - it's internal scoring guidance.

**Examples:**
| Question | Ideal Answer |
|----------|--------------|
| "Hoeveel jaar ervaring heb je met kassawerk?" | "We zoeken minstens 2 jaar ervaring in retail of horeca. Bonus als ze snel kunnen werken onder druk." |
| "Hoe ga je om met moeilijke klanten?" | "We willen concrete voorbeelden horen. Belangrijk: kalm blijven, empathie tonen, oplossingsgerichte aanpak." |

### Updating `ideal_answer` via Chat

Recruiters can update the ideal answer through natural language:

```typescript
await fetch('/interview/feedback', {
  method: 'POST',
  body: JSON.stringify({
    session_id: preScreening.session_id,
    message: "Voor vraag 2 wil ik dat we focussen op teamwerk en samenwerking"
  })
});
```

**Example prompts:**
- "Bij de klantenservice vraag zoeken we vooral naar empathie"
- "Pas de ideal answer aan voor vraag 3: we willen minstens 5 jaar ervaring"
- "Voor de ervaring vraag is het belangrijk dat ze specifieke voorbeelden geven"

---

## Usage

```typescript
// Load existing pre-screening - session is ready immediately
const preScreening = await fetch(`/vacancies/${vacancyId}/pre-screening`).then(r => r.json());

// Use session_id for AI editing
await fetch('/interview/feedback', {
  method: 'POST',
  body: JSON.stringify({
    session_id: preScreening.session_id,
    message: "Maak vraag 2 korter"
  })
});
```

---

## Session Handling Summary

| Scenario | Session Created By |
|----------|-------------------|
| New pre-screening | `/interview/generate` |
| Existing pre-screening | `GET /vacancies/{id}/pre-screening` (automatic) |

The `session_id` always equals the `vacancy_id`.
