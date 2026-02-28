# Frontend Brief: Ontology

## Overview

The backend provides a workspace-scoped ontology system — a knowledge graph where clients define their job categories, functions, required documents, skills, and the relationships between them. This feeds into the screening agents (knowing what documents to request per function) and provides structured context across the platform.

**Base URL:** `/workspaces/{workspaceId}/ontology`

All endpoints require authentication. All members can read; only admin/owner can write.

---

## Data Model

```
Workspace
  └── Types (category, job_function, document_type, skill, requirement)
        └── Entities (Transport, Chauffeur CE, Rijbewijs CE, ...)
              └── Relations (Chauffeur CE --requires--> Rijbewijs CE)
```

Each **entity** has: name, description, icon (Lucide name), color (hex), metadata (JSONB), external_id.

Each **relation** has: source entity, target entity, relation type, and metadata (e.g., `requirement_type`, `priority`, `condition`).

---

## TypeScript Types

```typescript
// ============================================================
// Entity Types (the "kinds" of entities)
// ============================================================

interface OntologyType {
  id: string;
  workspace_id: string;
  slug: string;            // 'category' | 'job_function' | 'document_type' | 'skill' | 'requirement'
  name: string;            // 'Categorie', 'Functie', 'Documenttype', ...
  name_plural: string | null;
  description: string | null;
  icon: string | null;     // Lucide icon name
  color: string | null;    // Hex color (#8B5CF6)
  sort_order: number;
  is_system: boolean;      // true = pre-seeded, cannot delete
  entity_count: number;    // how many entities of this type
  created_at: string;
  updated_at: string;
}

interface OntologyTypeCreate {
  slug: string;            // lowercase + underscores only
  name: string;
  name_plural?: string;
  description?: string;
  icon?: string;
  color?: string;          // must be #RRGGBB
  sort_order?: number;
}

interface OntologyTypeUpdate {
  name?: string;
  name_plural?: string;
  description?: string;
  icon?: string;
  color?: string;
  sort_order?: number;
}

// ============================================================
// Entities (the actual items: "Chauffeur CE", "Rijbewijs CE")
// ============================================================

interface OntologyEntity {
  id: string;
  workspace_id: string;
  type_id: string;
  type_slug: string;       // denormalized for convenience
  type_name: string;       // denormalized for convenience
  name: string;
  description: string | null;
  icon: string | null;     // overrides type-level icon if set
  color: string | null;    // overrides type-level color if set
  external_id: string | null;
  metadata: Record<string, any>;
  sort_order: number;
  is_active: boolean;
  relation_count: number;
  created_at: string;
  updated_at: string;
}

interface OntologyEntityDetail extends OntologyEntity {
  relations: OntologyRelation[];  // all relations where this entity is source or target
}

interface OntologyEntityCreate {
  type_slug: string;       // e.g., 'job_function', 'document_type'
  name: string;
  description?: string;
  icon?: string;
  color?: string;
  external_id?: string;
  metadata?: Record<string, any>;
  sort_order?: number;
}

interface OntologyEntityUpdate {
  name?: string;
  description?: string;
  icon?: string;
  color?: string;
  external_id?: string;
  metadata?: Record<string, any>;
  sort_order?: number;
  is_active?: boolean;
}

// ============================================================
// Relation Types
// ============================================================

interface OntologyRelationType {
  id: string;
  workspace_id: string;
  slug: string;            // 'belongs_to', 'requires', 'has_skill'
  name: string;            // 'Behoort tot', 'Vereist', 'Heeft vaardigheid'
  source_type_id: string | null;
  source_type_slug: string | null;  // constraint: only this type can be source
  target_type_id: string | null;
  target_type_slug: string | null;  // constraint: only this type can be target
  is_system: boolean;
  created_at: string;
}

interface OntologyRelationTypeCreate {
  slug: string;
  name: string;
  source_type_slug?: string;  // optional constraint
  target_type_slug?: string;  // optional constraint
}

// ============================================================
// Relations (connections between entities)
// ============================================================

interface OntologyRelation {
  id: string;
  workspace_id: string;
  source_entity_id: string;
  source_entity_name: string;
  source_type_slug: string;
  target_entity_id: string;
  target_entity_name: string;
  target_type_slug: string;
  relation_type_id: string;
  relation_type_slug: string;
  relation_type_name: string;
  metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
}

interface OntologyRelationCreate {
  source_entity_id: string;
  target_entity_id: string;
  relation_type_slug: string;  // 'requires', 'belongs_to', 'has_skill'
  metadata?: Record<string, any>;
}

interface OntologyRelationUpdate {
  metadata: Record<string, any>;
}

// ============================================================
// Graph (for visualization)
// ============================================================

interface OntologyGraphNode {
  id: string;
  name: string;
  type_slug: string;
  type_name: string;
  icon: string | null;     // effective icon (entity override or type fallback)
  color: string | null;    // effective color (entity override or type fallback)
  description: string | null;
  metadata: Record<string, any>;
  external_id: string | null;
}

interface OntologyGraphEdge {
  id: string;
  source: string;          // entity ID
  target: string;          // entity ID
  relation_type: string;   // slug
  relation_label: string;  // display name
  metadata: Record<string, any>;
}

interface OntologyGraph {
  nodes: OntologyGraphNode[];
  edges: OntologyGraphEdge[];
  types: OntologyType[];   // for legend rendering
  stats: Record<string, number>;  // { category: 5, job_function: 12, ... }
}

// ============================================================
// Overview
// ============================================================

interface OntologyOverview {
  types: OntologyType[];
  total_entities: number;
  total_relations: number;
}

// ============================================================
// Relation Metadata (for 'requires' relation type)
// ============================================================

type RequirementType = 'verplicht' | 'voorwaardelijk' | 'gewenst';

interface RequiresMetadata {
  requirement_type: RequirementType;
  priority: number;
  condition?: string;      // e.g., "Bij gevaarlijk transport"
}
```

---

## API Endpoints

### Overview & Graph

| Method | Endpoint | Response |
|--------|----------|----------|
| GET | `/ontology` | `OntologyOverview` |
| GET | `/ontology/graph` | `OntologyGraph` |

### Entity Types

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| GET | `/ontology/types` | - | `OntologyType[]` |
| POST | `/ontology/types` | `OntologyTypeCreate` | `OntologyType` |
| PATCH | `/ontology/types/{typeId}` | `OntologyTypeUpdate` | `OntologyType` |
| DELETE | `/ontology/types/{typeId}` | - | `{ success: true }` |

### Entities

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| GET | `/ontology/entities?type=&search=&active=&limit=&offset=` | - | `PaginatedResponse<OntologyEntity>` |
| POST | `/ontology/entities` | `OntologyEntityCreate` | `OntologyEntity` |
| GET | `/ontology/entities/{entityId}` | - | `OntologyEntityDetail` |
| PATCH | `/ontology/entities/{entityId}` | `OntologyEntityUpdate` | `OntologyEntity` |
| DELETE | `/ontology/entities/{entityId}` | - | `{ success: true }` |

**Query params for GET /entities:**
- `type` — Filter by type slug (e.g., `?type=job_function`)
- `search` — Search by name (case-insensitive)
- `active` — Filter by active status (default: `true`)
- `limit` / `offset` — Pagination (default: 100/0)

**Paginated response shape:**
```json
{
  "items": [...],
  "total": 45,
  "limit": 100,
  "offset": 0
}
```

### Relation Types

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| GET | `/ontology/relation-types` | - | `OntologyRelationType[]` |
| POST | `/ontology/relation-types` | `OntologyRelationTypeCreate` | `OntologyRelationType` |

### Relations

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| GET | `/ontology/relations?source_id=&target_id=&type=` | - | `OntologyRelation[]` |
| POST | `/ontology/relations` | `OntologyRelationCreate` | `OntologyRelation` |
| PATCH | `/ontology/relations/{relationId}` | `OntologyRelationUpdate` | `OntologyRelation` |
| DELETE | `/ontology/relations/{relationId}` | - | `{ success: true }` |

**Query params for GET /relations:**
- `source_id` — Filter by source entity UUID
- `target_id` — Filter by target entity UUID
- `type` — Filter by relation type slug

---

## Pages & Views

### 1. Ontology Overview Page (`/ontology`)

Fetch: `GET /ontology`

Shows all entity types as cards with counts, plus totals. Each card links to the filtered entity list.

```
┌──────────────────────────────────────────────────────┐
│  Ontology                              [Graph] [+New]│
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │
│  │ 📁 Categorie │ │ 💼 Functies  │ │ 📄 Document  │   │
│  │   ën        │ │             │ │   types     │   │
│  │  5 types    │ │  12 types   │ │  24 types   │   │
│  └─────────────┘ └─────────────┘ └─────────────┘   │
│                                                      │
│  ┌─────────────┐ ┌─────────────┐                    │
│  │ ⭐ Vaardig   │ │ ✅ Vereisten │                    │
│  │   heden     │ │             │                    │
│  │  Coming soon│ │  45 types   │                    │
│  └─────────────┘ └─────────────┘                    │
│                                                      │
│  Job Functions                          [Bekijk alle]│
│  ├── Chauffeur CE  (Transport, 5 documenten)        │
│  ├── Chauffeur C   (Transport, 4 documenten)        │
│  ├── Magazijnmedewerker (Logistics, 3 documenten)   │
│  └── ...                                            │
└──────────────────────────────────────────────────────┘
```

### 2. Graph View (`/ontology/graph`)

Fetch: `GET /ontology/graph`

Full interactive graph visualization. Suggested library: **React Flow**, **D3.js**, or **Cytoscape.js**.

```
┌──────────────────────────────────────────────────────┐
│  ← Ontology > Graph     ● Verplicht ● Voorw. ● Gew. │
├──────────────────────────────────────────────────────┤
│                                                      │
│  [Workspace]──┬──[Transport]──┬──[Chauffeur CE]──┬── │
│               │               │                  │   │
│               │               └──[Chauffeur C]   │   │
│               │                                  │   │
│               ├──[Logistics]──...                ├──[Identiteitskaart]
│               │                                  ├──[Rijbewijs CE]
│               ├──[Healthcare]──...               ├──[Code 95]
│               │                                  ├──[ADR Certificaat]
│               └──[Office]──...                   └──[Medisch Attest]
│                                                      │
└──────────────────────────────────────────────────────┘
```

**Key behaviors:**
- Nodes are colored by their `type` (use `types[]` from response for legend)
- Edge style based on `metadata.requirement_type`:
  - `verplicht` → solid red line
  - `voorwaardelijk` → dashed orange line
  - `gewenst` → dotted blue line
- **Hover on a node** → highlight all connected edges and nodes (dim others)
- **Click on a node** → open entity detail panel/page
- Node shape/icon from `icon` field (Lucide icon names)

**Building the graph from API response:**
```typescript
const { nodes, edges, types, stats } = await fetchGraph(workspaceId);

// nodes → graph nodes (position with layout algorithm)
// edges → graph edges (source/target are entity IDs)
// types → legend items (slug, name, color)
// stats → badge counts per type
```

### 3. Entity Type List (`/ontology?type=job_function`)

Fetch: `GET /ontology/entities?type=job_function`

Table/list view of all entities within a type. Supports search and pagination.

```
┌──────────────────────────────────────────────────────┐
│  ← Functies (12)                    [🔍 Zoeken] [+]  │
├──────────────────────────────────────────────────────┤
│  Name              │ Category    │ Documenten │      │
│  ──────────────────┼─────────────┼────────────┼────  │
│  Chauffeur CE      │ Transport   │ 5          │  →   │
│  Chauffeur C       │ Transport   │ 4          │  →   │
│  Magazijnmedewerker│ Logistics   │ 3          │  →   │
│  Heftruckchauffeur │ Logistics   │ 4          │  →   │
│  Verpleegkundige   │ Healthcare  │ 4          │  →   │
│  ...               │             │            │      │
└──────────────────────────────────────────────────────┘
```

To show the "Category" column and "Documenten" count, use the entity detail endpoint or fetch relations filtered by source.

### 4. Entity Detail Page (`/ontology/entities/{id}`)

Fetch: `GET /ontology/entities/{entityId}`

Shows entity info + tabs for related data. The `relations` array in the response contains all connections.

```
┌──────────────────────────────────────────────────────┐
│  ← Functies > Chauffeur CE                  [Graph]  │
├──────────────────────────────────────────────────────┤
│  🚛 Chauffeur CE                                     │
│  Job Function · Transport                            │
│  Vrachtwagenchauffeur met CE-rijbewijs...            │
│                                                      │
│  [Overzicht] [Documenten 5] [Vereisten] [Relaties]  │
├──────────────────────────────────────────────────────┤
│  Vereiste Documenten                    [+ Toevoegen]│
│  ─────────────────────────────────────────────────── │
│  Document          │ Type          │ Voorwaarde  │ # │
│  ──────────────────┼───────────────┼─────────────┼── │
│  Identiteitskaart  │ ● Verplicht   │ -           │ 1 │
│  Rijbewijs CE      │ ● Verplicht   │ -           │ 2 │
│  Code 95           │ ● Verplicht   │ -           │ 3 │
│  ADR Certificaat   │ ◐ Voorwaarde. │ Bij gevaar. │ 4 │
│  Medisch Attest    │ ○ Gewenst     │ -           │ 5 │
└──────────────────────────────────────────────────────┘
```

**Rendering the documents tab:**
```typescript
const entity = await fetchEntityDetail(workspaceId, entityId);

// Filter relations where this entity is source and relation type is 'requires'
const documentRequirements = entity.relations
  .filter(r => r.source_entity_id === entityId && r.relation_type_slug === 'requires')
  .sort((a, b) => (a.metadata.priority ?? 99) - (b.metadata.priority ?? 99));

// Each relation has:
// - target_entity_name: "Rijbewijs CE"
// - metadata.requirement_type: "verplicht" | "voorwaardelijk" | "gewenst"
// - metadata.priority: 1, 2, 3, ...
// - metadata.condition: "Bij gevaarlijk transport" (optional)
```

### 5. Add/Edit Document Requirement Dialog

When adding a document requirement to a job function:

```
┌─────────────────────────────────────────┐
│  Identiteitskaart                    ✕  │
│  Bewerk de vereisten voor dit document  │
│                                         │
│  [Algemeen] [Weergave] [Geavanceerd]   │
├─────────────────────────────────────────┤
│                                         │
│  Vereiste Type                          │
│  [● Verplicht          ▾]              │
│                                         │
│  Prioriteit                             │
│  [1                     ]              │
│  Volgorde waarin documenten worden      │
│  opgevraagd.                            │
│                                         │
│  Voorwaarde (optioneel)                 │
│  [Bij gevaarlijk transport    ]         │
│                                         │
│  [Verwijderen]    [Annuleren] [Opslaan] │
└─────────────────────────────────────────┘
```

**Creating a new requirement:**
```typescript
await fetch(`/workspaces/${workspaceId}/ontology/relations`, {
  method: 'POST',
  body: JSON.stringify({
    source_entity_id: jobFunctionId,     // e.g., Chauffeur CE
    target_entity_id: documentTypeId,    // e.g., Rijbewijs CE
    relation_type_slug: 'requires',
    metadata: {
      requirement_type: 'verplicht',     // 'verplicht' | 'voorwaardelijk' | 'gewenst'
      priority: 1,
      condition: null,                   // or "Bij gevaarlijk transport"
    }
  })
});
```

**Updating requirement metadata:**
```typescript
await fetch(`/workspaces/${workspaceId}/ontology/relations/${relationId}`, {
  method: 'PATCH',
  body: JSON.stringify({
    metadata: {
      requirement_type: 'voorwaardelijk',
      priority: 4,
      condition: 'Bij gevaarlijk transport',
    }
  })
});
```

**Deleting a requirement:**
```typescript
await fetch(`/workspaces/${workspaceId}/ontology/relations/${relationId}`, {
  method: 'DELETE',
});
```

---

## Default Seeded Data

Every workspace comes pre-seeded with:

### 5 Entity Types

| Slug | Name | Plural | Icon | Color |
|------|------|--------|------|-------|
| `category` | Categorie | Categorieën | folder | #8B5CF6 |
| `job_function` | Functie | Functies | briefcase | #3B82F6 |
| `document_type` | Documenttype | Documenttypes | file-text | #10B981 |
| `skill` | Vaardigheid | Vaardigheden | star | #F59E0B |
| `requirement` | Vereiste | Vereisten | check-circle | #EF4444 |

### 3 Relation Types

| Slug | Name | Source Type | Target Type |
|------|------|-------------|-------------|
| `belongs_to` | Behoort tot | job_function | category |
| `requires` | Vereist | job_function | document_type |
| `has_skill` | Heeft vaardigheid | job_function | skill |

Relation types have optional **source/target constraints**. The backend validates these — e.g., you can only create a `requires` relation from a `job_function` to a `document_type`.

### Demo Data (via POST /demo/reset)

After reset, the demo workspace is populated with 5 categories, 12 job functions, 15 document types, and 46 relations (12 belongs_to + 34 requires).

---

## Edge Color / Style Mapping

For graph and table rendering, map `metadata.requirement_type` to visual styles:

```typescript
const requirementStyles: Record<RequirementType, { color: string; label: string; style: string }> = {
  verplicht:       { color: '#EF4444', label: 'Verplicht',       style: 'solid' },
  voorwaardelijk:  { color: '#F59E0B', label: 'Voorwaardelijk',  style: 'dashed' },
  gewenst:         { color: '#3B82F6', label: 'Gewenst',         style: 'dotted' },
};
```

For the graph legend (top-right corner), render these three items as colored circles/lines.

---

## Entity Color / Icon Resolution

Entities can override their type's color and icon. Use this logic:

```typescript
function getEffectiveVisuals(entity: OntologyEntity | OntologyGraphNode, types: OntologyType[]) {
  const type = types.find(t => t.slug === entity.type_slug);
  return {
    color: entity.color ?? type?.color ?? '#6B7280',
    icon: entity.icon ?? type?.icon ?? 'circle',
  };
}
```

The graph endpoint already resolves this server-side — `OntologyGraphNode.color` and `icon` are the effective values.

---

## Notes

- **Soft delete**: Deleting an entity sets `is_active = false`. It disappears from lists and graph but is preserved in the database. Relations pointing to it are filtered out of queries.
- **System types cannot be deleted**: The 5 default entity types and 3 default relation types have `is_system = true`. The DELETE endpoint returns a 400 error for these.
- **Relation uniqueness**: Only one relation of a given type can exist between two entities. Creating a duplicate returns a database conflict error.
- **No self-relations**: An entity cannot relate to itself (enforced by database constraint).
- **Icons**: All icon names are [Lucide](https://lucide.dev/icons) identifiers. Use `lucide-react` to render them.
