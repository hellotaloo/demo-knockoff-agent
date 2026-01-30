# Displaying AI Thinking/Reasoning

The interview generator uses "thinking mode" which streams the model's reasoning process before generating questions. Displaying this makes the ~10s wait feel shorter and gives users insight into the AI's analysis.

## Overview

| Endpoint | Thinking Events | Model |
|----------|----------------|-------|
| `/interview/generate` | Yes - streams reasoning | gemini-2.5-flash (with thinking) |
| `/interview/feedback` | No - fast edits only | gemini-2.5-flash-lite |

## SSE Event Types

```typescript
interface SSEEvent {
  type: 'status' | 'thinking' | 'complete' | 'error';
  status?: 'thinking' | 'tool_call';
  message?: string;
  content?: string;        // Thinking content (for type: 'thinking')
  interview?: Interview;
  session_id?: string;
}
```

## Event Flow

```
1. status: { status: 'thinking', message: 'Vacature analyseren...' }
2. thinking: { content: 'De vacature vraagt om...' }  // May arrive multiple times
3. status: { status: 'tool_call', message: 'Vragen genereren...' }
4. complete: { message: '...', interview: {...}, session_id: '...' }
```

## Example Thinking Content

The AI streams its analysis in Dutch:

```
De vacature vraagt om een productiemedewerker met ervaring in een 2-ploegensysteem. 
Dit is een duidelijk knockout criterium. Daarnaast wordt fysiek werk genoemd 
("tillen tot 25kg") wat ook een harde eis is. De locatie is Diest, dus bereikbaarheid 
is belangrijk. Voor kwalificatievragen focus ik op technische ervaring en motivatie.
```

## React Implementation

### State Management

```tsx
interface GeneratorState {
  isLoading: boolean;
  thinkingContent: string;
  statusMessage: string;
}

const [state, setState] = useState<GeneratorState>({
  isLoading: false,
  thinkingContent: '',
  statusMessage: '',
});
```

### Event Handler

```tsx
const handleSSEEvent = (event: SSEEvent) => {
  switch (event.type) {
    case 'status':
      setState(prev => ({ 
        ...prev, 
        statusMessage: event.message || '' 
      }));
      break;
      
    case 'thinking':
      // IMPORTANT: Append content, it streams in chunks
      setState(prev => ({ 
        ...prev, 
        thinkingContent: prev.thinkingContent + (event.content || '') 
      }));
      break;
      
    case 'complete':
      setState(prev => ({ 
        ...prev, 
        isLoading: false,
        thinkingContent: '', // Clear for next generation
      }));
      // Handle interview result...
      break;
      
    case 'error':
      setState(prev => ({ 
        ...prev, 
        isLoading: false,
        thinkingContent: '',
      }));
      // Handle error...
      break;
  }
};
```

### Starting Generation

```tsx
const handleGenerate = async (vacancyText: string) => {
  // Reset state before starting
  setState({
    isLoading: true,
    thinkingContent: '',
    statusMessage: 'Starten...',
  });
  
  try {
    const result = await generateInterview(vacancyText, handleSSEEvent);
    // Handle result...
  } catch (error) {
    // Handle error...
  }
};
```

## UI Component

```tsx
import { Loader2, Brain } from 'lucide-react';

// Inside your component's return:
{state.isLoading && (
  <div className="bg-muted/50 rounded-lg p-4 space-y-3 animate-in fade-in">
    {/* Status indicator */}
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />
      <span>{state.statusMessage || 'Analyseren...'}</span>
    </div>
    
    {/* Thinking content */}
    {state.thinkingContent && (
      <div className="border-l-2 border-primary/30 pl-3 space-y-1">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wide">
          <Brain className="h-3 w-3" />
          <span>AI Redenering</span>
        </div>
        <p className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">
          {state.thinkingContent}
        </p>
      </div>
    )}
  </div>
)}
```

## Collapsible Version (Optional)

If you want users to be able to collapse the thinking:

```tsx
import { ChevronDown, ChevronUp, Brain, Loader2 } from 'lucide-react';

const [showThinking, setShowThinking] = useState(true);

{state.isLoading && (
  <div className="bg-muted/50 rounded-lg p-4 space-y-3">
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>{state.statusMessage}</span>
      </div>
      
      {state.thinkingContent && (
        <button 
          onClick={() => setShowThinking(!showThinking)}
          className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
        >
          <Brain className="h-3 w-3" />
          {showThinking ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
      )}
    </div>
    
    {showThinking && state.thinkingContent && (
      <div className="text-sm text-muted-foreground border-l-2 border-primary/20 pl-3 whitespace-pre-wrap">
        {state.thinkingContent}
      </div>
    )}
  </div>
)}
```

## UX Best Practices

1. **Show immediately** - Display thinking as soon as it arrives, don't buffer
2. **Subtle styling** - Use muted colors so it doesn't compete with the final result
3. **Auto-scroll** - If content overflows, consider auto-scrolling to show latest
4. **Clear on complete** - Reset thinking content when generation finishes
5. **Smooth transitions** - Use `animate-in fade-in` for appearing content
6. **Monospace optional** - Consider `font-mono text-xs` for a more "technical" feel

## Performance Notes

- Thinking typically streams ~1-3KB of text
- Events arrive in chunks, usually 2-5 events total
- Total thinking time: ~8-12 seconds depending on vacancy complexity
- The thinking content is in Dutch (nl-BE) to match the generated questions
