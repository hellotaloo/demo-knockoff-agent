# Frontend Integration Guide

This document describes how to connect the demo-admin frontend to the interview generator backend.

## Backend API

**Base URL:** `https://taloo-agent-182581851450.europe-west1.run.app`

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

## Interview Data Structure

```typescript
interface InterviewQuestion {
  id: string;      // "ko_1", "ko_2", "qual_1", etc.
  question: string;
}

interface Interview {
  intro: string;
  knockout_questions: InterviewQuestion[];
  knockout_failed_action: string;
  qualification_questions: InterviewQuestion[];
  final_action: string;
  approved_ids: string[];  // IDs of questions that are locked
}
```

## SSE Event Types

| Type | Description | Fields |
|------|-------------|--------|
| `status` | Progress update | `status`: "thinking" \| "tool_call", `message`: string |
| `thinking` | Agent reasoning (optional) | `content`: string |
| `complete` | Final result | `message`: string, `interview`: Interview, `session_id`: string |
| `error` | Error occurred | `message`: string |

## Implementation Steps

### Step 1: Create API Client

Create `lib/interview-api.ts`:

```typescript
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'https://taloo-agent-182581851450.europe-west1.run.app';

export interface InterviewQuestion {
  id: string;
  question: string;
}

export interface Interview {
  intro: string;
  knockout_questions: InterviewQuestion[];
  knockout_failed_action: string;
  qualification_questions: InterviewQuestion[];
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
```

### Step 2: Add Environment Variable

Add to `.env.local`:
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
Sessions are stored in memory. If the backend restarts, sessions are lost. This is fine for demos - just generate new questions.
