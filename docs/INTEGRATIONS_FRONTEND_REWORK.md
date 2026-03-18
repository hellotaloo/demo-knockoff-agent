# Integrations - Frontend Rework

## Problem

The credential form fields are hardcoded per provider in the frontend. This means every time the backend changes which fields a provider needs, the frontend has to be manually updated. This is wrong.

## Solution

Use the **OpenAPI schema** from the backend to dynamically render the form. The backend already exposes the exact fields and their metadata at:

```
GET /openapi.json
```

The relevant schemas are under `components.schemas`:
- `ConnexysCredentialsRequest` — fields for Connexys
- `MicrosoftCredentialsRequest` — fields for Microsoft

Each field has `type`, `description`, and `required` metadata that the frontend should use to generate the form dynamically.

## How to implement

1. Fetch the OpenAPI spec once (cache it — it doesn't change at runtime)
2. For each provider slug, map to its schema name:
   ```ts
   const schemaMap: Record<string, string> = {
     connexys: "ConnexysCredentialsRequest",
     microsoft: "MicrosoftCredentialsRequest",
   }
   ```
3. Read the schema's `properties` and `required` array to render form fields
4. Field rendering rules:
   - Field name contains `secret`, `password`, or `token` → `type="password"`
   - Everything else → `type="text"`
   - Use the `description` as placeholder/helper text
   - Use the `required` array to mark mandatory fields

## Example

The backend currently returns this for `ConnexysCredentialsRequest`:

```json
{
  "properties": {
    "instance_url": {
      "type": "string",
      "description": "Salesforce instance URL, e.g. https://company.my.salesforce.com"
    },
    "consumer_key": {
      "type": "string",
      "description": "Connected App Consumer Key"
    },
    "consumer_secret": {
      "type": "string",
      "description": "Connected App Consumer Secret"
    }
  },
  "required": ["instance_url", "consumer_key", "consumer_secret"]
}
```

The frontend should render 3 fields from this. If tomorrow the backend adds or removes a field, the form updates automatically — zero frontend changes needed.

## Remove

- All hardcoded field definitions per provider
- The static field tables/configs for Connexys and Microsoft
