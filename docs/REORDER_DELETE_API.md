# Reorder & Delete API Endpoints

Instructions for implementing the reorder and delete functionality in the frontend.

## Overview

Two new endpoints have been added to directly update question order and delete questions **without invoking the AI agent**. This provides instant responses (~50ms) for UI operations like drag-and-drop.

---

## Endpoints

### 1. Reorder Questions

Reorder knockout and/or qualification questions instantly.

```
POST /interview/reorder
Content-Type: application/json
```

**Request Body:**

```json
{
  "session_id": "uuid-from-generate",
  "knockout_order": ["ko_1", "ko_3", "ko_2"],
  "qualification_order": ["qual_2", "qual_1", "qual_3"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | Yes | The session ID from `/interview/generate` |
| `knockout_order` | string[] | No | New order of knockout question IDs |
| `qualification_order` | string[] | No | New order of qualification question IDs |

**Note:** Only include the arrays you want to reorder. Omit the field to keep that list unchanged.

**Success Response (200):**

```json
{
  "status": "success",
  "interview": {
    "intro": "...",
    "knockout_questions": [
      { "id": "ko_1", "question": "..." },
      { "id": "ko_3", "question": "..." },
      { "id": "ko_2", "question": "..." }
    ],
    "knockout_failed_action": "...",
    "qualification_questions": [...],
    "final_action": "...",
    "approved_ids": []
  }
}
```

**Error Responses:**

| Status | Detail |
|--------|--------|
| 404 | `"Session not found"` |
| 400 | `"No interview in session"` |
| 400 | `"Unknown question ID: ko_99"` |

---

### 2. Delete Question

Delete a single question by ID.

```
POST /interview/delete
Content-Type: application/json
```

**Request Body:**

```json
{
  "session_id": "uuid-from-generate",
  "question_id": "ko_2"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | Yes | The session ID from `/interview/generate` |
| `question_id` | string | Yes | The question ID to delete (e.g., `"ko_1"`, `"qual_2"`) |

**Success Response (200):**

```json
{
  "status": "success",
  "deleted": "ko_2",
  "interview": {
    "intro": "...",
    "knockout_questions": [...],
    "qualification_questions": [...],
    ...
  }
}
```

**Error Responses:**

| Status | Detail |
|--------|--------|
| 404 | `"Session not found"` |
| 404 | `"Question not found: ko_99"` |
| 400 | `"No interview in session"` |

**Note:** If the deleted question was in `approved_ids`, it is automatically removed from that list.

---

## Frontend Implementation

### API Client Functions

Add these functions to your API client (e.g., `lib/interview-api.ts`):

```typescript
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8080';

/**
 * Reorder questions instantly (no agent call).
 * Use for drag-and-drop reordering.
 */
export async function reorderQuestions(
  sessionId: string,
  knockoutOrder?: string[],
  qualificationOrder?: string[]
): Promise<Interview> {
  const response = await fetch(`${BACKEND_URL}/interview/reorder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      knockout_order: knockoutOrder,
      qualification_order: qualificationOrder,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to reorder questions');
  }

  const data = await response.json();
  return data.interview;
}

/**
 * Delete a question instantly (no agent call).
 */
export async function deleteQuestion(
  sessionId: string,
  questionId: string
): Promise<Interview> {
  const response = await fetch(`${BACKEND_URL}/interview/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      question_id: questionId,
    }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to delete question');
  }

  const data = await response.json();
  return data.interview;
}
```

### Usage Examples

**After drag-and-drop completes:**

```typescript
// User reordered knockout questions via drag-and-drop
const newKnockoutOrder = ['ko_1', 'ko_3', 'ko_2'];

try {
  const updatedInterview = await reorderQuestions(sessionId, newKnockoutOrder);
  setInterview(updatedInterview);
} catch (error) {
  console.error('Reorder failed:', error);
  // Revert UI to previous state
}
```

**On delete button click:**

```typescript
const handleDelete = async (questionId: string) => {
  try {
    const updatedInterview = await deleteQuestion(sessionId, questionId);
    setInterview(updatedInterview);
  } catch (error) {
    console.error('Delete failed:', error);
  }
};
```

### Optimistic Updates Pattern

For the best UX, update the UI immediately and revert on error:

```typescript
const handleReorder = async (oldIndex: number, newIndex: number) => {
  // Save current state for rollback
  const previousQuestions = [...questions];
  
  // Optimistic update
  const reordered = arrayMove(questions, oldIndex, newIndex);
  setQuestions(reordered);
  
  try {
    await reorderQuestions(sessionId, reordered.map(q => q.id));
  } catch (error) {
    // Rollback on failure
    setQuestions(previousQuestions);
    toast.error('Failed to save new order');
  }
};
```

---

## Important Notes

1. **Instant Response**: These endpoints don't invoke the AI agent, so they return in ~50ms
2. **Agent Sync**: The session state is updated directly, so the agent sees the changes on the next feedback message
3. **ID Format**: Knockout questions use `ko_1`, `ko_2`, etc. Qualification questions use `qual_1`, `qual_2`, etc.
4. **Validation**: The backend validates that all IDs in the reorder request exist in the current interview
