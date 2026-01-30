# Frontend Integration Guide

This document describes how to connect the demo-admin frontend to the interview generator backend.

## Environment Setup

### Local Development vs Production

| Environment | Frontend | Backend |
|-------------|----------|---------|
| **Local** | `http://localhost:3000` | `http://localhost:8080` |
| **Production** | `https://demo-admin-indol.vercel.app` | `https://taloo-agent-182581851450.europe-west1.run.app` |

### Frontend Environment Variables

**For local development** - create `.env.local`:
```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8080
```

**For production on Vercel** - add in Vercel Dashboard → Settings → Environment Variables:
```env
NEXT_PUBLIC_BACKEND_URL=https://taloo-agent-182581851450.europe-west1.run.app
```

The `NEXT_PUBLIC_` prefix makes the variable available in browser/client code.

### Running Locally

**Terminal 1 - Backend:**
```bash
cd taloo-demo
source .venv/bin/activate
uvicorn app:app --reload --port 8080
```

**Terminal 2 - Frontend:**
```bash
cd demo-admin
npm run dev
```

Then open `http://localhost:3000` to test.

### API Client Fallback

The API client uses an environment variable with a fallback:
```typescript
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8080';
```

This means:
- If `NEXT_PUBLIC_BACKEND_URL` is set → use that URL
- If not set → default to `http://localhost:8080` for local dev

---

## Backend API

**Base URL:** `https://taloo-agent-182581851450.europe-west1.run.app` (production) or `http://localhost:8080` (local)

### Endpoints

#### 1. Generate Interview Questions (SSE)

```
POST /interview/generate
Content-Type: application/json
```

**Request:**
```json
{
  "vacancy_text": "Full vacancy text here...",
  "session_id": "optional-uuid-to-reuse-session"
}
```

**Response:** Server-Sent Events stream

```
data: {"type": "status", "status": "thinking", "message": "Vacature analyseren..."}
data: {"type": "status", "status": "tool_call", "message": "Vragen genereren..."}
data: {"type": "complete", "message": "Ik heb de vragen gegenereerd...", "interview": {...}, "session_id": "uuid"}
data: [DONE]
```

#### 2. Send Feedback (SSE)

```
POST /interview/feedback
Content-Type: application/json
```

**Request:**
```json
{
  "session_id": "uuid-from-generate",
  "message": "Verwijder de vraag over communicatie"
}
```

**Response:** Server-Sent Events stream (same format as generate)

#### 3. Get Session State

```
GET /interview/session/{session_id}
```

**Response:**
```json
{
  "session_id": "uuid",
  "interview": {
    "intro": "...",
    "knockout_questions": [...],
    "qualification_questions": [...],
    ...
  }
}
```

#### 4. Reorder Questions (Direct Update)

Instantly reorder questions without invoking the agent. Ideal for drag-and-drop UI.

```
POST /interview/reorder
Content-Type: application/json
```

**Request:**
```json
{
  "session_id": "uuid-from-generate",
  "knockout_order": ["ko_1", "ko_3", "ko_2"],
  "qualification_order": ["qual_2", "qual_1", "qual_3"]
}
```

Both `knockout_order` and `qualification_order` are optional. Only provide the ones you want to reorder.

**Response:**
```json
{
  "status": "success",
  "interview": { ... }
}
```

#### 5. Delete Question (Direct Update)

Instantly delete a question without invoking the agent.

```
POST /interview/delete
Content-Type: application/json
```

**Request:**
```json
{
  "session_id": "uuid-from-generate",
  "question_id": "ko_2"
}
```

**Response:**
```json
{
  "status": "success",
  "deleted": "ko_2",
  "interview": { ... }
}

## Interview Data Structure

```typescript
type ChangeStatus = 'new' | 'updated' | 'unchanged';

interface KnockoutQuestion {
  id: string;           // "ko_1", "ko_2", etc.
  question: string;
  change_status?: ChangeStatus;  // "new", "updated", or "unchanged"
}

interface QualificationQuestion {
  id: string;           // "qual_1", "qual_2", etc.
  question: string;
  ideal_answer: string; // What we want to hear - used by AI to score responses
  change_status?: ChangeStatus;  // "new", "updated", or "unchanged"
}

interface Interview {
  intro: string;
  knockout_questions: KnockoutQuestion[];
  knockout_failed_action: string;
  qualification_questions: QualificationQuestion[];
  final_action: string;
  approved_ids: string[];  // IDs of questions that are locked
}
```

### The `ideal_answer` Field

Each qualification question includes an `ideal_answer` field that describes what the recruiter wants to hear in a good response. This is used by the downstream AI agent to score candidate answers.

**Example:**
```json
{
  "id": "qual_1",
  "question": "Heb je ervaring met kassawerk en het afrekenen van klanten?",
  "ideal_answer": "We zoeken iemand met concrete kassaervaring in retail of horeca. Bonus als ze fouten kunnen afhandelen of snel kunnen werken onder druk.",
  "is_modified": true
}
```

**How recruiters can update it via chat:**
- "Voor vraag 2 wil ik dat we focussen op teamwerk"
- "Bij de vraag over ervaring zoeken we eigenlijk iemand met minstens 3 jaar"
- "Pas de ideal answer aan voor de klantenservice vraag: we willen concrete voorbeelden horen"

## SSE Event Types

| Type | Description | Fields |
|------|-------------|--------|
| `status` | Progress update | `status`: "thinking" \| "tool_call", `message`: string |
| `thinking` | Agent reasoning (streamed) | `content`: string |
| `complete` | Final result | `message`: string, `interview`: Interview, `session_id`: string |
| `error` | Error occurred | `message`: string |

> **Displaying AI Thinking**: See [THINKING_DISPLAY.md](./THINKING_DISPLAY.md) for how to display the AI's reasoning process during generation.

## Implementation Steps

### Step 1: Create API Client

Create `lib/interview-api.ts`:

```typescript
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'https://taloo-agent-182581851450.europe-west1.run.app';

export type ChangeStatus = 'new' | 'updated' | 'unchanged';

export interface KnockoutQuestion {
  id: string;
  question: string;
  change_status?: ChangeStatus;  // "new", "updated", or "unchanged"
}

export interface QualificationQuestion {
  id: string;
  question: string;
  ideal_answer: string;  // What we want to hear - used by AI to score responses
  change_status?: ChangeStatus;  // "new", "updated", or "unchanged"
}

export interface Interview {
  intro: string;
  knockout_questions: KnockoutQuestion[];
  knockout_failed_action: string;
  qualification_questions: QualificationQuestion[];
  final_action: string;
  approved_ids: string[];
}

export interface SSEEvent {
  type: 'status' | 'thinking' | 'complete' | 'error';
  status?: 'thinking' | 'tool_call';
  message?: string;
  content?: string;
  interview?: Interview;
  session_id?: string;
}

export type StatusCallback = (event: SSEEvent) => void;

export async function generateInterview(
  vacancyText: string,
  onEvent: StatusCallback,
  sessionId?: string
): Promise<{ interview: Interview; sessionId: string }> {
  const response = await fetch(`${BACKEND_URL}/interview/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 
      vacancy_text: vacancyText,
      session_id: sessionId 
    }),
  });

  if (!response.ok) {
    throw new Error('Failed to generate interview');
  }

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();
  
  let interview: Interview | null = null;
  let finalSessionId = sessionId || '';

  if (!reader) throw new Error('No response body');

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split('\n');

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        if (data === '[DONE]') continue;

        try {
          const event: SSEEvent = JSON.parse(data);
          onEvent(event);

          if (event.type === 'complete') {
            interview = event.interview || null;
            finalSessionId = event.session_id || finalSessionId;
          }
        } catch (e) {
          console.error('Failed to parse SSE event:', e);
        }
      }
    }
  }

  if (!interview) throw new Error('No interview generated');
  return { interview, sessionId: finalSessionId };
}

export async function sendFeedback(
  sessionId: string,
  message: string,
  onEvent: StatusCallback
): Promise<Interview> {
  const response = await fetch(`${BACKEND_URL}/interview/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  });

  if (!response.ok) throw new Error('Failed to send feedback');

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();
  let interview: Interview | null = null;

  if (!reader) throw new Error('No response body');

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split('\n');

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        if (data === '[DONE]') continue;

        try {
          const event: SSEEvent = JSON.parse(data);
          onEvent(event);
          if (event.type === 'complete') {
            interview = event.interview || null;
          }
        } catch (e) {
          console.error('Failed to parse SSE event:', e);
        }
      }
    }
  }

  if (!interview) throw new Error('No interview returned');
  return interview;
}

/**
 * Reorder questions instantly (no agent call).
 * Use this for drag-and-drop UI.
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

### Step 2: Add Environment Variable

See [Environment Setup](#environment-setup) section above.

**Local** (`.env.local`):
```
NEXT_PUBLIC_BACKEND_URL=http://localhost:8080
```

**Production** (Vercel Environment Variables):
```
NEXT_PUBLIC_BACKEND_URL=https://taloo-agent-182581851450.europe-west1.run.app
```

### Step 3: Update GenerateInterviewChat Component

Replace the mock implementation in `components/chat/GenerateInterviewChat.tsx`:

1. Import the API client:
```typescript
import { generateInterview, sendFeedback, Interview, SSEEvent } from '@/lib/interview-api';
```

2. Add state for session and status:
```typescript
const [sessionId, setSessionId] = useState<string | null>(null);
const [currentStatus, setCurrentStatus] = useState<string>('');
```

3. Create event handler:
```typescript
const handleSSEEvent = (event: SSEEvent) => {
  if (event.type === 'status') {
    setCurrentStatus(event.message || '');
  }
};
```

4. Replace `handleProceed` with real API call:
```typescript
const handleProceed = async () => {
  addUserMessage('Ja, ga verder');
  setIsLoading(true);
  setConversationState('analyzing');
  setCurrentStatus('Vacature analyseren...');

  try {
    const { interview, sessionId: newSessionId } = await generateInterview(
      vacancyText,  // Pass the full vacancy text as prop
      handleSSEEvent
    );

    setSessionId(newSessionId);
    
    // Convert to frontend format
    const questions = [
      ...interview.knockout_questions.map(q => ({
        id: q.id,
        text: q.question,
        type: 'knockout' as const,
      })),
      ...interview.qualification_questions.map(q => ({
        id: q.id,
        text: q.question,
        type: 'qualifying' as const,
      })),
    ];
    
    setGeneratedQuestions(questions);
    setConversationState('questions');
    onQuestionsGenerated?.(questions);
    
    addAssistantMessage(
      'Op basis van de vacature heb ik de volgende screeningvragen opgesteld:',
      'questions',
      questions
    );
  } catch (error) {
    console.error('Failed to generate interview:', error);
    addAssistantMessage('Er is een fout opgetreden. Probeer het opnieuw.');
  } finally {
    setIsLoading(false);
    setCurrentStatus('');
  }
};
```

5. Replace feedback handling in `handleSubmit`:
```typescript
} else if ((conversationState === 'questions' || conversationState === 'feedback') && sessionId) {
  addUserMessage(originalInput);
  setConversationState('feedback');
  setIsLoading(true);
  setCurrentStatus('Feedback verwerken...');

  try {
    const updatedInterview = await sendFeedback(sessionId, originalInput, handleSSEEvent);
    
    const questions = [
      ...updatedInterview.knockout_questions.map(q => ({
        id: q.id,
        text: q.question,
        type: 'knockout' as const,
      })),
      ...updatedInterview.qualification_questions.map(q => ({
        id: q.id,
        text: q.question,
        type: 'qualifying' as const,
      })),
    ];
    
    setGeneratedQuestions(questions);
    onQuestionsGenerated?.(questions);
    
    addAssistantMessage(
      'Ik heb de vragen aangepast:',
      'questions',
      questions
    );
  } catch (error) {
    addAssistantMessage('Er is een fout opgetreden. Probeer het opnieuw.');
  } finally {
    setIsLoading(false);
    setCurrentStatus('');
  }
}
```

6. Update loading indicator to show status:
```typescript
{isLoading && (
  <div className="max-w-[610px] flex items-center gap-2">
    <RefreshCw className="w-4 h-4 text-gray-400 animate-spin" />
    <span className="text-sm text-gray-500">
      {currentStatus || 'Aan het nadenken...'}
    </span>
  </div>
)}
```

### Step 4: Add vacancyText Prop

Update the component props to accept the full vacancy text:

```typescript
interface GenerateInterviewChatProps {
  vacancyTitle: string;
  vacancyText: string;  // Add this
  onComplete?: (questions: GeneratedQuestion[]) => void;
  onQuestionsGenerated?: (questions: GeneratedQuestion[]) => void;
  interviewTitle?: string;
}
```

Then update the page that uses this component to pass the vacancy text.

## Status Display Suggestions

Show different icons based on status:

```typescript
{isLoading && currentStatus && (
  <div className="flex items-center gap-2">
    {currentStatus.includes('genereren') || currentStatus.includes('aanpassen') ? (
      <Wrench className="w-4 h-4 text-orange-500 animate-pulse" />
    ) : (
      <Brain className="w-4 h-4 text-purple-500 animate-pulse" />
    )}
    <span className="text-sm text-gray-500">{currentStatus}</span>
  </div>
)}
```

Import icons from lucide-react:
```typescript
import { Brain, Wrench } from 'lucide-react';
```

## Testing

1. Start the frontend: `npm run dev`
2. Navigate to an interview generation page
3. Click "Ja, analyseer de vacature"
4. Observe status updates: "Vacature analyseren..." → "Vragen genereren..." → Questions appear
5. Send feedback: "Verwijder de eerste vraag"
6. Observe status: "Feedback verwerken..." → "Vragen aanpassen..." → Updated questions

## Troubleshooting

### CORS Issues
The backend allows all origins (`*`). If you still see CORS errors, check that the request is going to the correct URL.

### SSE Not Working
Ensure your hosting (Vercel) doesn't buffer SSE responses. The backend sends `X-Accel-Buffering: no` header.

### Session Not Found
Sessions are stored in the database. They persist across backend restarts.
