# Interview Questions API - Frontend Integration Guide

Endpoints for directly manipulating interview questions without invoking the agent. Use these for instant UI updates when users drag-to-reorder, delete, or add questions manually.

## Overview

| Endpoint | Purpose |
|----------|---------|
| `POST /interview/add` | Add a new question |
| `POST /interview/delete` | Delete a question |
| `POST /interview/reorder` | Reorder questions |
| `GET /interview/state/{session_id}` | Get current interview state |

All endpoints update the session state directly. The agent will be aware of these changes on subsequent invocations via the injected `[SYSTEEM:]` context.

---

## Add Question

Add a knockout or qualification question to the interview.

```
POST /interview/add
Content-Type: application/json
```

### Request Body

```typescript
interface AddQuestionRequest {
  session_id: string;
  question_type: "knockout" | "qualification";
  question: string;
  ideal_answer?: string;  // Required for qualification questions
}
```

### Examples

**Add a knockout question:**

```json
{
  "session_id": "abc123-session-id",
  "question_type": "knockout",
  "question": "Heb je een rijbewijs B?"
}
```

**Add a qualification question:**

```json
{
  "session_id": "abc123-session-id",
  "question_type": "qualification",
  "question": "Hoeveel jaar ervaring heb je met CNC machines?",
  "ideal_answer": "Minstens 2 jaar hands-on ervaring. Bonus als ze specifieke machinetypes kunnen noemen."
}
```

### Response

```typescript
interface AddQuestionResponse {
  status: "success";
  added: string;           // Generated ID (e.g., "ko_3" or "qual_4")
  question: {
    id: string;
    question: string;
    ideal_answer?: string;  // Only for qualification
    change_status: "new";
  };
  interview: Interview;    // Full updated interview object
}
```

**Example response:**

```json
{
  "status": "success",
  "added": "ko_3",
  "question": {
    "id": "ko_3",
    "question": "Heb je een rijbewijs B?",
    "change_status": "new"
  },
  "interview": { ... }
}
```

### Error Responses

| Status | Detail |
|--------|--------|
| 400 | `question_type must be 'knockout' or 'qualification'` |
| 400 | `ideal_answer is required for qualification questions` |
| 400 | `No interview in session` |

| 404 | `Session not found` |

### Frontend Implementation

```typescript
async function addQuestion(
  sessionId: string,
  type: "knockout" | "qualification",
  question: string,
  idealAnswer?: string
) {
  const response = await fetch("/interview/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      question_type: type,
      question,
      ideal_answer: idealAnswer,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }

  const data = await response.json();
  
  // Update your local state with the new question
  // The question is added at the END of the list
  return data;
}
```

### UI Considerations

1. **New questions appear at the end** - The question is appended to the list
2. **ID is auto-generated** - Don't let users specify IDs; the backend finds the next available `ko_N` or `qual_N`
3. **change_status is "new"** - Use this to highlight newly added questions in the UI
4. **Reorder after adding** - If the user wants the question elsewhere, call `/interview/reorder` after adding

---

## Delete Question

Remove a knockout or qualification question.

```
POST /interview/delete
Content-Type: application/json
```

### Request Body

```typescript
interface DeleteQuestionRequest {
  session_id: string;
  question_id: string;  // e.g., "ko_1" or "qual_2"
}
```

### Example

```json
{
  "session_id": "abc123-session-id",
  "question_id": "ko_2"
}
```

### Response

```json
{
  "status": "success",
  "deleted": "ko_2",
  "interview": { ... }
}
```

### Error Responses

| Status | Detail |
|--------|--------|
| 400 | `No interview in session` |
| 404 | `Session not found` |
| 404 | `Question not found: ko_99` |

### Frontend Implementation

```typescript
async function deleteQuestion(sessionId: string, questionId: string) {
  const response = await fetch("/interview/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      question_id: questionId,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }

  return response.json();
}
```

---

## Reorder Questions

Change the order of knockout and/or qualification questions.

```
POST /interview/reorder
Content-Type: application/json
```

### Request Body

```typescript
interface ReorderRequest {
  session_id: string;
  knockout_order?: string[];       // List of IDs in new order
  qualification_order?: string[];  // List of IDs in new order
}
```

You can reorder one or both lists in a single call.

### Example

```json
{
  "session_id": "abc123-session-id",
  "knockout_order": ["ko_1", "ko_3", "ko_2"],
  "qualification_order": ["qual_2", "qual_1", "qual_3"]
}
```

### Response

```json
{
  "status": "success",
  "interview": { ... }
}
```

### Frontend Implementation (Drag & Drop)

```typescript
async function reorderQuestions(
  sessionId: string,
  knockoutOrder?: string[],
  qualificationOrder?: string[]
) {
  const response = await fetch("/interview/reorder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      knockout_order: knockoutOrder,
      qualification_order: qualificationOrder,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail);
  }

  return response.json();
}

// Example: After drag-and-drop in a knockout questions list
function onDragEnd(result: DropResult) {
  if (!result.destination) return;

  const items = Array.from(knockoutQuestions);
  const [reordered] = items.splice(result.source.index, 1);
  items.splice(result.destination.index, 0, reordered);

  // Optimistic UI update
  setKnockoutQuestions(items);

  // Sync with backend
  reorderQuestions(sessionId, items.map(q => q.id));
}
```

---

## Get Interview State

Retrieve the current interview state for a session.

```
GET /interview/state/{session_id}
```

### Response

```typescript
interface Interview {
  intro: string;
  knockout_questions: {
    id: string;
    question: string;
    change_status?: "new" | "updated" | "unchanged";
  }[];
  knockout_failed_action: string;
  qualification_questions: {
    id: string;
    question: string;
    ideal_answer: string;
    change_status?: "new" | "updated" | "unchanged";
  }[];
  final_action: string;
  approved_ids: string[];
}
```

### Error Responses

| Status | Detail |
|--------|--------|
| 400 | `No interview in session` |
| 404 | `Session not found` |

---

## State Synchronization

### How it works

1. **Session state is the source of truth** - All question data lives in the ADK session
2. **Direct endpoints update state immediately** - No agent invocation, instant response
3. **Agent reads current state** - When the user sends feedback via `/interview/feedback`, the current questions are injected as a `[SYSTEEM:]` message
4. **Agent respects external changes** - Order changes, additions, and deletions are all reflected

### Recommended Flow

```
┌─────────────────┐
│  User drags to  │
│  reorder in UI  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ POST /reorder   │  ← Instant, no agent
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  UI updates     │
│  immediately    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ User types:     │
│ "Make Q2 shorter"│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ POST /feedback  │  ← Agent sees new order
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Agent edits Q2 │
│  keeps order    │
└─────────────────┘
```

### Optimistic Updates

For the best UX, update the UI immediately before the API call completes:

```typescript
function handleAddQuestion(question: string, type: "knockout" | "qualification") {
  // 1. Generate temporary ID for optimistic update
  const tempId = `temp_${Date.now()}`;
  const tempQuestion = { id: tempId, question, change_status: "new" };

  // 2. Optimistic UI update
  if (type === "knockout") {
    setKnockoutQuestions([...knockoutQuestions, tempQuestion]);
  } else {
    setQualificationQuestions([...qualificationQuestions, tempQuestion]);
  }

  // 3. API call
  addQuestion(sessionId, type, question, idealAnswer)
    .then((data) => {
      // 4. Replace temp ID with real ID
      if (type === "knockout") {
        setKnockoutQuestions(prev =>
          prev.map(q => q.id === tempId ? data.question : q)
        );
      }
    })
    .catch((error) => {
      // 5. Rollback on error
      if (type === "knockout") {
        setKnockoutQuestions(prev => prev.filter(q => q.id !== tempId));
      }
      showError(error.message);
    });
}
```

---

## Complete TypeScript Types

```typescript
// Request types
interface AddQuestionRequest {
  session_id: string;
  question_type: "knockout" | "qualification";
  question: string;
  ideal_answer?: string;
}

interface DeleteQuestionRequest {
  session_id: string;
  question_id: string;
}

interface ReorderRequest {
  session_id: string;
  knockout_order?: string[];
  qualification_order?: string[];
}

// Response types
interface AddQuestionResponse {
  status: "success";
  added: string;
  question: KnockoutQuestion | QualificationQuestion;
  interview: Interview;
}

interface DeleteQuestionResponse {
  status: "success";
  deleted: string;
  interview: Interview;
}

interface ReorderResponse {
  status: "success";
  interview: Interview;
}

// Interview types
interface KnockoutQuestion {
  id: string;
  question: string;
  change_status?: "new" | "updated" | "unchanged";
}

interface QualificationQuestion {
  id: string;
  question: string;
  ideal_answer: string;
  change_status?: "new" | "updated" | "unchanged";
}

interface Interview {
  intro: string;
  knockout_questions: KnockoutQuestion[];
  knockout_failed_action: string;
  qualification_questions: QualificationQuestion[];
  final_action: string;
  approved_ids: string[];
}
```
