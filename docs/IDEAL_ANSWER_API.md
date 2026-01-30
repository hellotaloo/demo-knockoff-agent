# Ideal Answer Field - Frontend Integration

## Overview

Qualification questions now include an `ideal_answer` field that guides the AI when scoring candidate responses.

---

## Database Migration (Required)

Run this SQL to add the column:

```sql
ALTER TABLE pre_screening_questions 
ADD COLUMN ideal_answer TEXT;
```

---

## Data Structure

```typescript
type ChangeStatus = 'new' | 'updated' | 'unchanged';

interface QualificationQuestion {
  id: string;              // "qual_1", "qual_2", etc.
  question: string;        // Question shown to candidate
  ideal_answer: string;    // Internal scoring guidance (NOT shown to candidates)
  change_status?: ChangeStatus;  // "new", "updated", or "unchanged"
}
```

**Example response:**
```json
{
  "qualification_questions": [
    {
      "id": "qual_1",
      "question": "Heb je ervaring met kassawerk en het afrekenen van klanten?",
      "ideal_answer": "We zoeken iemand met concrete kassaervaring in retail of horeca. Bonus als ze fouten kunnen afhandelen.",
      "change_status": "new"
    },
    {
      "id": "qual_2",
      "question": "Hoe ga je om met moeilijke klanten?",
      "ideal_answer": "We willen concrete voorbeelden horen. Belangrijk: kalm blijven, empathie tonen, oplossingsgerichte aanpak.",
      "change_status": "unchanged"
    }
  ]
}
```

### `change_status` Values

| Value | Meaning | UI Suggestion |
|-------|---------|---------------|
| `"new"` | Question was just added | 🆕 "New" badge |
| `"updated"` | Question text or ideal_answer was edited | ✏️ "Updated" badge |
| `"unchanged"` | No changes to this question | No badge |

---

## Updating via Chat

Recruiters can update the `ideal_answer` through natural language in the feedback chat:

```typescript
await fetch('/interview/feedback', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_id: sessionId,
    message: "Voor vraag 2 wil ik dat we focussen op teamwerk"
  })
});
```

**Example prompts:**
| User says | Result |
|-----------|--------|
| "Voor vraag 2 wil ik dat we focussen op teamwerk" | Updates `ideal_answer` for qual_2 |
| "Bij de klantenservice vraag zoeken we vooral empathie" | Updates relevant question's `ideal_answer` |
| "Pas de ideal answer aan voor vraag 3: minstens 5 jaar ervaring" | Explicit update |

---

## UI Suggestions

### Display
- Show as collapsible/expandable hint below each qualification question
- Use subtle styling (light gray, smaller font)
- Icon with tooltip on hover is also an option

### Example UI mockup
```
┌─────────────────────────────────────────────────────────┐
│ Heb je ervaring met kassawerk?                          │
│                                                         │
│ 💡 We zoeken concrete ervaring in retail/horeca...      │  ← ideal_answer
└─────────────────────────────────────────────────────────┘
```

### Editing
Two options:
1. **Chat-based**: Recruiter types feedback in chat (already implemented)
2. **Inline edit**: Add edit icon next to `ideal_answer` that opens a text field

---

## Important Notes

- `ideal_answer` is **never shown to candidates** - it's internal scoring guidance
- The AI generates an `ideal_answer` automatically when creating questions
- Recruiters can refine it via chat feedback
- Use `change_status` to show visual badges:
  - `"new"` → new question just added
  - `"updated"` → question or ideal_answer was edited
  - `"unchanged"` → no changes
