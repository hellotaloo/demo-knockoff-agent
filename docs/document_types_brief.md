# Ontology API — Frontend Brief

## Overview

The Ontology API is a generic reference data system. It provides entities (document types, job functions, skills, etc.) with parent-child hierarchies and category grouping. Currently supports `document_type` — more types will be added.

All endpoints live under `/ontology`. Entity-type-specific fields (like `requires_front_back`) are in a generic `metadata` object so the shape stays consistent as new types are added.

## Available Entity Types

| Type | Label | Description | Status |
|------|-------|-------------|--------|
| `document_type` | Documenttypes | Document & certificate types for candidates | Live |
| `job_function` | Functies | Job function taxonomy | Planned |
| `skill` | Vaardigheden | Skills & competencies | Planned |

## Document Type Categories

| Category | Description | Examples |
|----------|-------------|----------|
| `identity` | Identity documents | ID-kaart, Paspoort, Verblijfsdocument |
| `certificate` | Work certificates & licenses | Rijbewijs, Heftruckbrevet, Arbeidsvergunning, VCA |
| `financial` | Financial documents | SIS-kaart, Studentenkaart, Fiscale fiche |
| `other` | Other documents | Diploma |

## API Endpoints

### `GET /ontology` — Overview of available types

Returns all registered entity types with counts and available categories. Use this to discover what entity types exist and build navigation.

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `workspace_id` | `uuid` | *required* | Workspace to scope results |

**Response:**
```json
{
  "types": [
    {
      "type": "document_type",
      "label": "Documenttypes",
      "description": "Document- en certificaattypes voor kandidaten",
      "total": 43,
      "categories": ["certificate", "financial", "identity", "other"]
    }
  ]
}
```

---

### `GET /ontology/entities` — List entities by type

Returns parent entities with nested children. The `type` param determines which entity type to query.

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | `string` | *required* | Entity type (`document_type`) |
| `workspace_id` | `uuid` | *required* | Workspace to scope results |
| `category` | `string?` | `null` | Filter by category |
| `include_children` | `boolean` | `true` | Nest children under parents |
| `include_inactive` | `boolean` | `false` | Include soft-deleted entities |
| `limit` | `int` | `200` | Max items (1-1000) |

**Response:**
```json
{
  "type": "document_type",
  "items": [
    {
      "id": "dfb19596-...",
      "type": "document_type",
      "slug": "id_card",
      "name": "ID-kaart",
      "description": null,
      "category": "identity",
      "icon": "credit-card",
      "is_default": true,
      "is_active": true,
      "sort_order": 1,
      "metadata": {
        "is_verifiable": true,
        "requires_front_back": true
      },
      "children": [],
      "children_count": 0
    },
    {
      "id": "a1b2c3d4-...",
      "type": "document_type",
      "slug": "rijbewijs",
      "name": "Rijbewijs",
      "category": "certificate",
      "icon": "car",
      "is_default": true,
      "sort_order": 3,
      "metadata": {
        "prato_flex_type_id": "10",
        "is_verifiable": true,
        "requires_front_back": true
      },
      "children": [
        {
          "id": "e5f6a7b8-...",
          "slug": "prato_10_AM",
          "name": "AM",
          "category": "certificate",
          "sort_order": 0,
          "metadata": {
            "prato_flex_type_id": "10",
            "prato_flex_detail_type_id": "AM"
          }
        },
        {
          "id": "c9d0e1f2-...",
          "slug": "prato_10_B",
          "name": "B",
          "category": "certificate",
          "sort_order": 0,
          "metadata": {
            "prato_flex_type_id": "10",
            "prato_flex_detail_type_id": "B"
          }
        }
      ],
      "children_count": 12
    }
  ],
  "total": 43,
  "categories": ["certificate", "financial", "identity", "other"]
}
```

---

### `GET /ontology/entities/{id}` — Get single entity

Returns a single entity with its children.

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `include_children` | `boolean` | `true` | Nest children |

**Response:** Same shape as a single item from the list endpoint.

## Frontend Usage Notes

- **Category filter tabs:** Use the `categories` array from the list response to render filter tabs/chips. Don't hardcode — categories vary per entity type and may grow.
- **Parent/child display:** Parents are the main rows. If `children_count > 0`, show an expandable section or dropdown with the detail types.
- **`is_default` flag:** Entities marked as default are pre-selected when configuring document collection for a vacancy.
- **`metadata` object:** Type-specific fields. For `document_type`:
  - `requires_front_back` (bool) — document upload should ask for front + back images
  - `is_verifiable` (bool) — can be sent through AI fraud detection (`POST /documents/verify`)
  - `prato_flex_type_id` (string) — external Prato Flex code, don't display to users
  - `prato_flex_detail_type_id` (string) — child-level Prato code
- **Workspace ID:** Currently all data lives under `00000000-0000-0000-0000-000000000001`.
