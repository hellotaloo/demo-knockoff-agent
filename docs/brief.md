# Architecture Visualization - Frontend Brief

## Goal

Build a visually appealing graph visualization of the Taloo backend architecture. Make it look cool.

## API Endpoint

```
GET /architecture
```

Returns JSON with nodes, edges, and groups for rendering an interactive architecture diagram.

## Data Structure

```typescript
interface ArchitectureResponse {
  nodes: ArchitectureNode[];   // 69 components
  edges: ArchitectureEdge[];   // 84 relationships
  groups: ArchitectureGroup[]; // 5 layers
  metadata: { stats: ArchitectureStats };
}
```

### Nodes (Components)

Each node has:
- `id` - Unique ID like `router:vacancies`, `service:vacancy`, `agent:cv_analyzer`
- `type` - One of: `router`, `service`, `repository`, `agent`, `external`
- `name` - Display name
- `layer` - Which layer it belongs to
- `file_path` - Source file location (optional)
- `description` - What it does

### Edges (Relationships)

- `source` / `target` - Node IDs
- `type` - Relationship type: `uses`, `calls`, `integrates`, `stores`
- `label` - Optional label like "webhook"

### Groups (Layers)

| Layer | Color | Description |
|-------|-------|-------------|
| API Layer | `#4CAF50` (green) | 23 FastAPI routers |
| Services | `#2196F3` (blue) | 19 business logic services |
| Repositories | `#FF9800` (orange) | 12 database access layers |
| AI Agents | `#9C27B0` (purple) | 9 Gemini-powered agents |
| External | `#607D8B` (gray) | 6 external integrations (VAPI, Twilio, etc.) |

## Suggested Libraries

- **React Flow** - Best for interactive node diagrams
- **D3.js** - Maximum customization
- **vis.js** - Easy clustering/grouping
- **Cytoscape.js** - Great for large graphs

## Layout Ideas

1. **Layered/Hierarchical** - Stack layers vertically (API at top, External at bottom)
2. **Force-directed** - Let physics arrange nodes, group by layer
3. **Radial** - External services in center, layers as concentric rings

## Features to Consider

- Hover for component details
- Click to highlight connected nodes
- Filter by layer
- Search nodes
- Zoom/pan
- Dark mode support
- Animated edges showing data flow direction

## Example Fetch

```typescript
const response = await fetch('/architecture');
const data: ArchitectureResponse = await response.json();

// Group nodes by layer for rendering
const nodesByLayer = data.nodes.reduce((acc, node) => {
  (acc[node.layer] ||= []).push(node);
  return acc;
}, {});
```

Make it beautiful!
