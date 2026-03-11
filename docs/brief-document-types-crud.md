# Brief — Document Types CRUD

**Date:** 2026-03-11
**Status:** Ready for implementation

---

## Context

Workspace admins need to manage document types directly from the UI. This covers creating, editing, and deleting both **parent document types** (top-level) and **child document types** (subtypes).

All endpoints are under `/ontology/entities` and require a `workspace_id`.

---

## Part 1 — Parent Document Types

### Create a parent

```
POST /ontology/entities?workspace_id={id}
{
  "slug": "mijn_document",        // auto-generated from name, editable
  "name": "Mijn Document",
  "category": "identity",         // see categories below
  "icon": "file-text",            // Lucide icon name, optional
  "is_verifiable": false,
  "is_default": false,
  "scan_mode": "single",
  "sort_order": 0
}
```

**Response:** `201` — full entity object

---

### Update a parent

```
PATCH /ontology/entities/{id}
{
  "name": "Nieuwe naam",
  "category": "certificate",
  "icon": "award",
  "is_verifiable": true,
  "is_default": true,
  "scan_mode": "front_back",
  "is_active": false              // to deactivate without deleting
}
```

All fields optional — only send what changed.

---

### Delete a parent

```
DELETE /ontology/entities/{id}
```

Soft-delete — sets `is_active = false`. Also implicitly hides all children (they're filtered out by parent). No cascade needed.

---

### Fields exposed in the UI

| Field | Input type | Notes |
|---|---|---|
| `name` | Text input | Required |
| `slug` | Text input (collapsed/advanced) | Auto-generated, editable. Lowercase, underscores only. Must be unique per workspace. |
| `category` | Select | See options below |
| `icon` | Icon picker | Lucide icon name |
| `is_default` | Toggle | "Standaard aangevraagd bij kandidaten" |
| `is_verifiable` | Toggle | Triggers verification config section (see verification brief) |
| `scan_mode` | Segmented control | `single` / `front_back` / `multi_page` — only when `is_verifiable = true` |

### Category options

| Value | Label |
|---|---|
| `identity` | Identiteit |
| `certificate` | Certificaat |
| `financial` | Financieel |
| `other` | Overige |

---

## Part 2 — Child Document Types (Subtypes)

Children are document types linked to a parent via `parent_id`. They appear as subtypes in the panel list.

### Create a child

```
POST /ontology/entities?workspace_id={id}
{
  "slug": "rijbewijs_b",          // auto-generated from name
  "name": "Rijbewijs B",
  "parent_id": "{parent_id}",     // required — links to parent
  "category": "certificate",      // inherit from parent, not shown in UI
  "sort_order": 0
}
```

**Response:** `201` — full entity object (child has no `verification_config` or `scan_mode`)

---

### Update a child

```
PATCH /ontology/entities/{child_id}
{
  "name": "Rijbewijs B (herzien)",
  "sort_order": 2
}
```

Only `name` and `sort_order` are relevant for children. Do not expose `is_verifiable`, `scan_mode`, or `verification_config` — those live on the parent.

---

### Delete a child

```
DELETE /ontology/entities/{child_id}
```

Soft-delete — row disappears from the subtype list.

---

### Fields exposed in the UI (inline in subtype list)

| Field | Input type | Notes |
|---|---|---|
| `name` | Inline text input | Click to edit |
| `sort_order` | Drag handle | Reorder within list |

No other fields needed for children.

---

## Slug generation

Auto-generate slugs client-side from `name`:

```js
slug = name.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "")
```

Examples:
- `"Rijbewijs B"` → `"rijbewijs_b"`
- `"C3.2 afdruk"` → `"c32_afdruk"`

Append `_2`, `_3` etc. if a conflict occurs (handle 409 response from API).

---

## Error handling

| Status | Meaning | UI action |
|---|---|---|
| `409 Conflict` | Slug already exists | Show inline error, suggest alternative slug |
| `404 Not Found` | Entity doesn't exist | Show toast, remove from list |
| `422 Unprocessable` | Validation error | Show field-level errors |
