# Screening Chat API - Frontend Integration Guide

Real-time chat interface for testing the dynamic screening agent without WhatsApp.

## Endpoint

```
POST /screening/chat
Content-Type: application/json
```

Returns: `text/event-stream` (Server-Sent Events)

## Request Body

```typescript
interface ScreeningChatRequest {
  vacancy_id: string;           // UUID of the vacancy to screen for
  message: string;              // User's message (use "START" for first message)
  session_id?: string;          // Optional: reuse session for conversation continuity
  candidate_name?: string;      // Required for first message only
}
```

### First Message (Start Conversation)

```json
{
  "vacancy_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "START",
  "candidate_name": "Sarah"
}
```

### Subsequent Messages

```json
{
  "vacancy_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "returned-session-id",
  "message": "Ja, ik heb een werkvergunning"
}
```

## SSE Event Types

Events are sent as `data: {JSON}\n\n` format.

### Status Event
Processing indicator - show loading state.

```json
{
  "type": "status",
  "status": "thinking",
  "message": "Antwoord genereren..."
}
```

### Complete Event
Final response with agent message.

```json
{
  "type": "complete",
  "message": "Hoi Sarah! 👋 Leuk dat je hebt gesolliciteerd...",
  "session_id": "abc123-session-id"
}
```

**Important:** Save `session_id` for subsequent messages!

### Error Event
Something went wrong.

```json
{
  "type": "error",
  "message": "Vacancy not found"
}
```

### Stream End
```
data: [DONE]
```

## JavaScript Implementation

### Basic Example

```javascript
async function sendMessage(vacancyId, message, sessionId = null, candidateName = null) {
  const body = {
    vacancy_id: vacancyId,
    message: message,
  };
  
  if (sessionId) body.session_id = sessionId;
  if (candidateName) body.candidate_name = candidateName;

  const response = await fetch('/screening/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  
  let currentSessionId = sessionId;
  let agentMessage = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split('\n');

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        
        if (data === '[DONE]') {
          return { message: agentMessage, sessionId: currentSessionId };
        }

        try {
          const event = JSON.parse(data);
          
          switch (event.type) {
            case 'status':
              console.log('Status:', event.message);
              // Show loading indicator
              break;
              
            case 'complete':
              agentMessage = event.message;
              currentSessionId = event.session_id;
              break;
              
            case 'error':
              throw new Error(event.message);
          }
        } catch (e) {
          if (e instanceof SyntaxError) continue; // Ignore parse errors
          throw e;
        }
      }
    }
  }

  return { message: agentMessage, sessionId: currentSessionId };
}
```

### React Hook Example

```typescript
import { useState, useCallback } from 'react';

interface Message {
  role: 'user' | 'agent';
  content: string;
}

export function useScreeningChat(vacancyId: string) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendMessage = useCallback(async (
    message: string, 
    candidateName?: string
  ) => {
    setIsLoading(true);
    setError(null);
    
    // Add user message to chat
    setMessages(prev => [...prev, { role: 'user', content: message }]);

    try {
      const body: any = {
        vacancy_id: vacancyId,
        message: message,
      };
      
      if (sessionId) body.session_id = sessionId;
      if (candidateName) body.candidate_name = candidateName;

      const response = await fetch('/screening/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          
          const data = line.slice(6);
          if (data === '[DONE]') break;

          try {
            const event = JSON.parse(data);
            
            if (event.type === 'complete') {
              setMessages(prev => [...prev, { 
                role: 'agent', 
                content: event.message 
              }]);
              setSessionId(event.session_id);
            } else if (event.type === 'error') {
              setError(event.message);
            }
          } catch {
            // Ignore parse errors
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  }, [vacancyId, sessionId]);

  const startConversation = useCallback((candidateName: string) => {
    return sendMessage('START', candidateName);
  }, [sendMessage]);

  const resetChat = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    setError(null);
  }, []);

  return {
    messages,
    isLoading,
    error,
    sessionId,
    sendMessage,
    startConversation,
    resetChat,
  };
}
```

### Usage in Component

```tsx
function ScreeningChat({ vacancyId }: { vacancyId: string }) {
  const { 
    messages, 
    isLoading, 
    error, 
    sendMessage, 
    startConversation 
  } = useScreeningChat(vacancyId);
  
  const [input, setInput] = useState('');
  const [started, setStarted] = useState(false);

  const handleStart = async () => {
    await startConversation('Test Kandidaat');
    setStarted(true);
  };

  const handleSend = async () => {
    if (!input.trim()) return;
    await sendMessage(input);
    setInput('');
  };

  return (
    <div>
      {!started ? (
        <button onClick={handleStart}>Start Screening</button>
      ) : (
        <>
          <div className="messages">
            {messages.map((m, i) => (
              <div key={i} className={m.role}>
                {m.content}
              </div>
            ))}
            {isLoading && <div className="loading">Typing...</div>}
          </div>
          
          <input 
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyPress={e => e.key === 'Enter' && handleSend()}
            disabled={isLoading}
          />
          <button onClick={handleSend} disabled={isLoading}>
            Send
          </button>
        </>
      )}
      
      {error && <div className="error">{error}</div>}
    </div>
  );
}
```

## Vanilla HTML/JS Example

```html
<!DOCTYPE html>
<html>
<head>
  <title>Screening Test</title>
  <style>
    .chat { max-width: 400px; margin: 20px auto; }
    .messages { height: 400px; overflow-y: auto; border: 1px solid #ccc; padding: 10px; }
    .user { text-align: right; color: blue; margin: 5px 0; }
    .agent { text-align: left; color: green; margin: 5px 0; }
    .loading { color: gray; font-style: italic; }
    input { width: 70%; padding: 8px; }
    button { padding: 8px 16px; }
  </style>
</head>
<body>
  <div class="chat">
    <h2>Screening Test</h2>
    <div>
      <label>Vacancy ID: <input id="vacancyId" value="" /></label>
    </div>
    <div>
      <label>Candidate Name: <input id="candidateName" value="Test" /></label>
      <button onclick="startChat()">Start</button>
    </div>
    <hr>
    <div id="messages" class="messages"></div>
    <div>
      <input id="input" placeholder="Type your message..." onkeypress="if(event.key==='Enter')sendMsg()" />
      <button onclick="sendMsg()">Send</button>
    </div>
  </div>

  <script>
    let sessionId = null;
    const messagesDiv = document.getElementById('messages');
    const inputEl = document.getElementById('input');

    function addMessage(role, content) {
      const div = document.createElement('div');
      div.className = role;
      div.textContent = content;
      messagesDiv.appendChild(div);
      messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    async function streamChat(body) {
      const response = await fetch('/screening/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        for (const line of chunk.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6);
          if (data === '[DONE]') return;
          
          try {
            const event = JSON.parse(data);
            if (event.type === 'complete') {
              addMessage('agent', event.message);
              sessionId = event.session_id;
            } else if (event.type === 'error') {
              addMessage('agent', '❌ Error: ' + event.message);
            }
          } catch {}
        }
      }
    }

    async function startChat() {
      const vacancyId = document.getElementById('vacancyId').value;
      const candidateName = document.getElementById('candidateName').value;
      
      if (!vacancyId) {
        alert('Please enter a vacancy ID');
        return;
      }

      messagesDiv.innerHTML = '';
      sessionId = null;
      
      addMessage('loading', 'Starting conversation...');
      
      await streamChat({
        vacancy_id: vacancyId,
        message: 'START',
        candidate_name: candidateName,
      });
      
      // Remove loading message
      messagesDiv.querySelector('.loading')?.remove();
    }

    async function sendMsg() {
      const message = inputEl.value.trim();
      if (!message || !sessionId) return;
      
      inputEl.value = '';
      addMessage('user', message);
      addMessage('loading', 'Typing...');

      const vacancyId = document.getElementById('vacancyId').value;
      
      await streamChat({
        vacancy_id: vacancyId,
        session_id: sessionId,
        message: message,
      });
      
      messagesDiv.querySelector('.loading')?.remove();
    }
  </script>
</body>
</html>
```

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `Vacancy not found` | Invalid vacancy_id | Check UUID format |
| `No pre-screening found` | Vacancy has no screening config | Create pre-screening first |
| `Session not found` | Invalid/expired session_id | Start new conversation |
| `candidate_name required` | First message without name | Include candidate_name |

## Testing Tips

1. **Get a vacancy ID**: Call `GET /vacancies` to list available vacancies
2. **Check pre-screening exists**: Call `GET /vacancies/{id}/pre-screening` 
3. **Use demo data**: Call `POST /demo/seed` to create test vacancies with pre-screenings

## Related Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /vacancies` | List all vacancies |
| `GET /vacancies/{id}` | Get vacancy details |
| `GET /vacancies/{id}/pre-screening` | Get screening questions |
| `POST /demo/seed` | Create demo data |
