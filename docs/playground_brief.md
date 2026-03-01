# Playground Voice Agent — Frontend Brief

## Overview

The Playground page lets users demo the pre-screening voice agent directly in the browser. The backend provides a single endpoint that returns LiveKit connection details. The frontend connects via WebRTC using the LiveKit JS SDK — no phone call needed.

The agent runs the full pre-screening flow: greeting, consent, knockout questions, open questions, and scheduling. All in Dutch.

## API Endpoint

### `POST /playground/start` — Start a playground session

Returns a LiveKit access token. When the browser connects with this token, the room is auto-created and the voice agent starts automatically.

**Request:**
```json
{
  "vacancy_id": "3158c4d2-...",
  "candidate_name": "Test Kandidaat",
  "start_agent": "greeting",
  "require_consent": false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `vacancy_id` | `string` | *required* | UUID of the vacancy to use |
| `candidate_name` | `string` | `"Playground Kandidaat"` | Name the agent will use to address the caller |
| `start_agent` | `string?` | `null` | Skip to a specific interview step (see below) |
| `require_consent` | `boolean` | `false` | Whether the agent asks for GDPR consent at the start |

**`start_agent` values:**

| Value | Starts at | Skips |
|-------|-----------|-------|
| `null` / `"greeting"` | Greeting & intro | Nothing — full flow |
| `"screening"` | Knockout questions | Greeting, consent |
| `"open_questions"` | Qualification questions | Greeting, consent, knockout |
| `"scheduling"` | Interview scheduling | Everything except scheduling |

**Response:**
```json
{
  "success": true,
  "livekit_url": "wss://taloo-xxxxxx.livekit.cloud",
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "room_name": "playground-abc123def456"
}
```

**Error Responses:**

| Status | Error |
|--------|-------|
| 400 | Invalid vacancy ID |
| 400 | No pre-screening configured for this vacancy |
| 400 | Pre-screening not published |
| 400 | Pre-screening is offline |
| 404 | Vacancy not found |
| 500 | LIVEKIT_URL not configured |

## TypeScript Types

```typescript
interface PlaygroundStartRequest {
  vacancy_id: string;
  candidate_name?: string;    // Default: "Playground Kandidaat"
  start_agent?: "greeting" | "screening" | "open_questions" | "scheduling" | null;
  require_consent?: boolean;  // Default: false
}

interface PlaygroundStartResponse {
  success: boolean;
  livekit_url: string;   // WebSocket URL (wss://...)
  access_token: string;  // JWT — pass to room.connect()
  room_name: string;     // e.g. "playground-abc123def456"
}
```

## Frontend Integration

### Install

```bash
npm install livekit-client
```

### Connect to the agent

```typescript
import { Room, RoomEvent, Track, ConnectionState } from "livekit-client";

let room: Room | null = null;

const startPlayground = async (params: PlaygroundStartRequest) => {
  // 1. Get token from backend
  const res = await fetch("/playground/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const data: PlaygroundStartResponse = await res.json();

  // 2. Create and connect room
  room = new Room();
  await room.connect(data.livekit_url, data.access_token);

  // 3. Enable microphone (triggers browser permission prompt)
  await room.localParticipant.setMicrophoneEnabled(true);

  // 4. Subscribe to agent audio (auto-plays)
  room.on(RoomEvent.TrackSubscribed, (track) => {
    if (track.kind === Track.Kind.Audio) {
      track.attach(); // creates hidden <audio> element
    }
  });
};
```

### Disconnect

```typescript
const stopPlayground = () => {
  room?.disconnect();
  room = null;
};

// Also disconnect on page leave / component unmount
window.addEventListener("beforeunload", stopPlayground);
```

### Connection state & events

```typescript
// Track connection state for UI
room.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
  // "connecting" | "connected" | "reconnecting" | "disconnected"
  setConnectionState(state);
});

// Agent disconnected (conversation ended)
room.on(RoomEvent.ParticipantDisconnected, (participant) => {
  if (participant.identity.startsWith("agent-")) {
    // Agent finished — show "conversation ended" state
    setConversationEnded(true);
  }
});

// Room disconnected (cleanup complete)
room.on(RoomEvent.Disconnected, () => {
  setConnectionState("disconnected");
});
```

## Behavior

### Flow

1. User configures playground settings (vacancy, candidate name, start step, consent toggle)
2. User clicks the call button
3. Frontend calls `POST /playground/start`
4. On success: connect to LiveKit room, enable mic
5. Agent starts speaking automatically (greeting or whichever step was selected)
6. User has a voice conversation with the agent
7. When the agent finishes (or user hangs up): disconnect and show ended state

### Phone UI simulation

The frontend renders a phone mockup on the right side of the page. During the call:
- Show a "connected" / "in call" state with a timer
- Show a hang-up button (calls `room.disconnect()`)
- When the agent ends the conversation, the room auto-disconnects — handle this via `RoomEvent.Disconnected`

### Microphone permissions

The browser will prompt for microphone permission on first use. If denied:
- Show a message explaining that mic access is required
- The `setMicrophoneEnabled(true)` call will throw — catch it and show an error

```typescript
try {
  await room.localParticipant.setMicrophoneEnabled(true);
} catch (err) {
  // Microphone permission denied or not available
  showError("Microfoon toegang is vereist voor de demo");
  room.disconnect();
}
```

### No database records

Playground sessions are completely ephemeral. No candidates, applications, or screening conversations are created in the database. The agent's results webhook fires but is silently ignored by the backend.

## Notes

- The agent speaks Dutch (Flemish nl-BE) by default
- The agent supports language switching — if the user speaks English/French/etc., the agent will switch
- There is no timeout on the token — but the room auto-cleans up when the conversation ends
- Each `POST /playground/start` call creates a fresh room. Multiple concurrent sessions are fine.
- The `room_name` in the response can be used for display/debugging purposes
