# Recruiter Analyst API - Frontend Integration Guide

This document describes how to integrate the Recruiter Analyst streaming API into your frontend application.

## Overview

The Recruiter Analyst is an AI agent that provides data analysis, strategic advice, and recruitment optimization insights. It can query your recruitment data and provide actionable recommendations.

**Key Features:**
- Natural language queries in Dutch
- Real-time streaming responses (SSE)
- Session-based conversation memory
- Sub-agent delegation to data_query agent for database queries

---

## API Endpoints

**Base URL:** 
- Local: `http://localhost:8080`
- Production: `https://taloo-agent-182581851450.europe-west1.run.app`

### 1. Query the Analyst (SSE Streaming)

```
POST /data-query
Content-Type: application/json
```

**Request:**
```json
{
  "question": "Hoeveel sollicitaties hebben we vandaag ontvangen?",
  "session_id": "optional-uuid-for-conversation-context"
}
```

**Response:** Server-Sent Events stream

```
data: {"type": "status", "status": "thinking", "message": "Vraag analyseren..."}
data: {"type": "status", "status": "tool_call", "message": "Data ophalen..."}
data: {"type": "thinking", "content": "Agent reasoning..."}
data: {"type": "complete", "message": "Vandaag zijn er 12 sollicitaties binnengekomen...", "session_id": "uuid"}
data: [DONE]
```

### 2. Get Session State

```
GET /data-query/session/{session_id}
```

**Response:**
```json
{
  "session_id": "uuid",
  "state": {}
}
```

### 3. Delete Session (Start Fresh)

```
DELETE /data-query/session/{session_id}
```

**Response:**
```json
{
  "status": "success",
  "message": "Session deleted"
}
```

---

## SSE Event Types

| Type | Description | Fields |
|------|-------------|--------|
| `status` | Progress update | `status`: "thinking" \| "tool_call", `message`: string |
| `thinking` | Agent reasoning (optional) | `content`: string |
| `complete` | Final answer | `message`: string, `session_id`: string |
| `error` | Error occurred | `message`: string |

---

## Implementation

### TypeScript API Client

Create `lib/analyst-api.ts`:

```typescript
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8080';

export interface AnalystSSEEvent {
  type: 'status' | 'thinking' | 'complete' | 'error';
  status?: 'thinking' | 'tool_call';
  message?: string;
  content?: string;
  session_id?: string;
}

export type AnalystEventCallback = (event: AnalystSSEEvent) => void;

/**
 * Query the recruiter analyst with natural language.
 * Returns a streaming response via SSE.
 */
export async function queryAnalyst(
  question: string,
  onEvent: AnalystEventCallback,
  sessionId?: string
): Promise<{ message: string; sessionId: string }> {
  const response = await fetch(`${BACKEND_URL}/data-query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      session_id: sessionId,
    }),
  });

  if (!response.ok) {
    throw new Error('Failed to query analyst');
  }

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();

  let finalMessage = '';
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
          const event: AnalystSSEEvent = JSON.parse(data);
          onEvent(event);

          if (event.type === 'complete') {
            finalMessage = event.message || '';
            finalSessionId = event.session_id || finalSessionId;
          }
        } catch (e) {
          console.error('Failed to parse SSE event:', e);
        }
      }
    }
  }

  return { message: finalMessage, sessionId: finalSessionId };
}

/**
 * Get the current session state.
 */
export async function getAnalystSession(sessionId: string): Promise<{
  session_id: string;
  state: Record<string, unknown>;
}> {
  const response = await fetch(`${BACKEND_URL}/data-query/session/${sessionId}`);
  
  if (!response.ok) {
    throw new Error('Session not found');
  }
  
  return response.json();
}

/**
 * Delete an analyst session to start fresh.
 */
export async function deleteAnalystSession(sessionId: string): Promise<void> {
  const response = await fetch(`${BACKEND_URL}/data-query/session/${sessionId}`, {
    method: 'DELETE',
  });
  
  if (!response.ok) {
    throw new Error('Failed to delete session');
  }
}
```

### React Component Example

```tsx
'use client';

import { useState, useRef } from 'react';
import { queryAnalyst, AnalystSSEEvent } from '@/lib/analyst-api';
import { Send, Brain, Database, Loader2 } from 'lucide-react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export function RecruiterAnalystChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState('');
  const sessionIdRef = useRef<string | undefined>();

  const handleSSEEvent = (event: AnalystSSEEvent) => {
    if (event.type === 'status') {
      setStatus(event.message || '');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const question = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: question }]);
    setIsLoading(true);
    setStatus('Vraag analyseren...');

    try {
      const { message, sessionId } = await queryAnalyst(
        question,
        handleSSEEvent,
        sessionIdRef.current
      );

      sessionIdRef.current = sessionId;
      setMessages(prev => [...prev, { role: 'assistant', content: message }]);
    } catch (error) {
      console.error('Failed to query analyst:', error);
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: 'Er is een fout opgetreden. Probeer het opnieuw.' },
      ]);
    } finally {
      setIsLoading(false);
      setStatus('');
    }
  };

  const startNewConversation = () => {
    sessionIdRef.current = undefined;
    setMessages([]);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <h2 className="text-lg font-semibold">Recruitment Analist</h2>
        <button
          onClick={startNewConversation}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          Nieuw gesprek
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 py-8">
            <Brain className="w-12 h-12 mx-auto mb-4 text-gray-300" />
            <p>Stel een vraag over je recruitment data.</p>
            <p className="text-sm mt-2">
              Bijvoorbeeld: "Hoeveel sollicitaties deze week?" of "Welke vacature presteert het beste?"
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] rounded-lg px-4 py-2 ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-900'
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>
            </div>
          </div>
        ))}

        {/* Loading indicator */}
        {isLoading && (
          <div className="flex items-center gap-2 text-gray-500">
            {status.includes('ophalen') ? (
              <Database className="w-4 h-4 animate-pulse text-orange-500" />
            ) : (
              <Brain className="w-4 h-4 animate-pulse text-purple-500" />
            )}
            <span className="text-sm">{status}</span>
          </div>
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Stel een vraag..."
            className="flex-1 rounded-lg border px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
          >
            {isLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
```

---

## Example Questions

The analyst understands Dutch and can answer questions like:

### Data Queries
- "Hoeveel sollicitaties hebben we vandaag?"
- "Wat is onze qualification rate deze week?"
- "Welke vacature heeft de meeste kandidaten?"
- "Toon me de laatste 5 sollicitaties"

### Analysis
- "Waarom is onze completion rate laag?"
- "Welk kanaal presteert beter: WhatsApp of Voice?"
- "Analyseer de resultaten voor vacature X"

### Strategy
- "Hoe kunnen we meer kandidaten kwalificeren?"
- "Welke kandidaat moet ik als eerste bellen?"
- "Geef advies over het verbeteren van onze knockout vragen"

---

## Session Management

The analyst maintains conversation context within a session:

1. **First query**: Don't provide `session_id` - a new one will be created
2. **Follow-up queries**: Include the returned `session_id` to maintain context
3. **Start fresh**: Call `DELETE /data-query/session/{session_id}` or omit `session_id`

Example conversation flow:

```typescript
// First question - no session
const { sessionId } = await queryAnalyst("Hoeveel sollicitaties vandaag?", onEvent);

// Follow-up - uses same session for context
await queryAnalyst("En hoeveel daarvan zijn gekwalificeerd?", onEvent, sessionId);

// The analyst remembers "vandaag" from the first question
```

---

## Status Messages

Display appropriate UI feedback based on status:

| Status | Icon Suggestion | Meaning |
|--------|-----------------|---------|
| "Vraag analyseren..." | Brain (purple) | Agent is thinking |
| "Data ophalen..." | Database (orange) | Querying the database |

```tsx
{status.includes('ophalen') ? (
  <Database className="animate-pulse text-orange-500" />
) : (
  <Brain className="animate-pulse text-purple-500" />
)}
```

---

## Error Handling

The API returns errors in SSE format:

```
data: {"type": "error", "message": "Database connection failed"}
data: [DONE]
```

Handle errors gracefully in your event callback:

```typescript
const handleSSEEvent = (event: AnalystSSEEvent) => {
  if (event.type === 'error') {
    setError(event.message);
    // Show error toast or message
  }
  // ... handle other event types
};
```

---

## Testing

1. Start the backend:
   ```bash
   uvicorn app:app --reload --port 8080
   ```

2. Test with curl:
   ```bash
   curl -X POST http://localhost:8080/data-query \
     -H "Content-Type: application/json" \
     -d '{"question": "Hoeveel vacatures zijn er?"}'
   ```

3. Expected output:
   ```
   data: {"type": "status", "status": "thinking", "message": "Vraag analyseren..."}
   data: {"type": "status", "status": "tool_call", "message": "Data ophalen..."}
   data: {"type": "complete", "message": "Er zijn momenteel 3 actieve vacatures...", "session_id": "abc-123"}
   data: [DONE]
   ```
