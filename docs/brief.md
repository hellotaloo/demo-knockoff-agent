# Candidate Attributes — Manual Editing (Candidate Detail Panel)

The candidate detail panel allows recruiters to manually add, edit, and remove attributes.

## Adding a new attribute

1. Fetch available attribute types: `GET /workspaces/{workspace_id}/candidate-attribute-types?is_active=true`
2. Show a dropdown/picker with types not yet set on the candidate (filter out types already in `candidate.attributes`)
3. Render the appropriate input based on `data_type`:
   - `text` → text input
   - `boolean` → toggle/switch
   - `date` → date picker
   - `number` → number input
   - `select` → dropdown with options from the type's `options` array (show `label`, store `value`)
   - `multi_select` → multi-select/checkbox group from `options`
4. Save: `PUT /candidates/{candidate_id}/attributes` with `source: "manual"`

```typescript
// Example: recruiter sets "has own transport" manually
await fetch(`/candidates/${candidateId}/attributes`, {
  method: 'PUT',
  body: JSON.stringify({
    attribute_type_id: "...",   // the type's UUID
    value: "true",              // always a string
    source: "manual",
  })
})
```

## Editing an existing attribute

- Click on the attribute value to make it editable (inline edit)
- Same input rendering rules as above based on `data_type`
- Save via the same `PUT /candidates/{candidate_id}/attributes` endpoint (upserts by `attribute_type_id`)
- The `source` updates to `"manual"` when a recruiter overrides an agent-collected value

## Removing an attribute

- Show a delete/remove action on each attribute row
- Call: `DELETE /candidates/{candidate_id}/attributes/{attribute_id}`
- Returns 204 on success

## UI Considerations

- Group attributes by `category` with collapsible sections
- Show an "Add attribute" button that opens the type picker
- Show `source` badge to distinguish agent-collected vs manual values
- Agent-collected values that are manually overridden should show `source: "manual"` (the PUT upsert handles this automatically)
- Consider showing a confirmation when deleting an agent-collected attribute
