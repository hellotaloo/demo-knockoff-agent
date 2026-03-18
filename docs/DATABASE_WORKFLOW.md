# Database Workflow

How to work with databases, branches, and migrations in the Taloo project.

## Overview

Database schema is managed across two repositories:

- **taloo-backend** — Application code. Contains `src/database.py` which auto-creates schemas and runs bootstrap migrations on startup.
- **taloo-database** — Schema migrations and seed data. Connected to Supabase via GitHub integration, so pushing migration files triggers automatic deployment.

All schema changes go through Git-based migration files in `taloo-database`. Supabase picks them up automatically via its GitHub integration.

## Environments

| Environment | Project Ref | Branch | Used By |
|-------------|-------------|--------|---------|
| **Main / Staging** | `beniqwbanoqhxyrjwulg` | `main` | Cloud Run staging, local dev (default) |
| **Preview branches** | Auto-generated per PR | Per PR | Testing schema changes before merge |

Preview branches are created automatically by Supabase when you open a PR against `master` in the `taloo-database` repo. Each preview branch gets its own isolated database.

## Connection Strings

The `.env` file contains two sets of Supabase credentials:

### PostgreSQL connection (app queries)

```
DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<password>@aws-1-eu-west-1.pooler.supabase.com:5432/postgres
```

This is the **pooler** connection used by asyncpg for all application queries. The `postgresql+asyncpg://` prefix is stripped at runtime by `database.py`.

**Important:** Direct connections (`db.<ref>.supabase.co`) use IPv6 and do not work from most local machines. Always use the pooler hostname (`aws-1-eu-west-1.pooler.supabase.com`) for local development. Cloud Run can use direct connections since GCP supports IPv6.

### Supabase Auth (JWT verification)

```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<anon-key>
SUPABASE_JWT_SECRET=<jwt-secret>
```

Used for verifying JWTs from the frontend. These are tied to the project, not the branch — so they stay the same unless you switch to a completely different Supabase project.

## Switching Databases

Use the helper script to switch your local `.env` between main and preview branches:

```bash
# Switch to main DB
./scripts/switch-db.sh main

# Switch to a preview branch
./scripts/switch-db.sh preview <project-ref> <password>
```

**Where to find the preview branch ref and password:**

1. Go to Supabase Dashboard → your project → **Branches**
2. Click the preview branch
3. Go to **Connect** → **Connection Pooler** section
4. Copy the project ref (appears in the username as `postgres.<ref>`) and the password

## Creating Migrations

All DDL changes (CREATE TABLE, ALTER TABLE, etc.) must be migration files in the `taloo-database` repo.

### Step by step

1. Create a SQL file in `/taloo-database/supabase/migrations/` with timestamp prefix:

   ```
   YYYYMMDDHHMMSS_description.sql
   ```

   Example: `20260318160755_move_types_to_ontology_schema.sql`

2. Write your DDL statements in the file.

3. **For direct changes:** Commit and push to `master`. Supabase applies the migration to the main branch automatically.

4. **For changes you want to test first:** Create a feature branch, push the migration file, and open a PR against `master`. This triggers a preview branch (see next section).

**NEVER use Supabase MCP `apply_migration`** — always use the Git workflow so migrations are tracked in version control.

## Testing Schema Changes with Preview Branches

1. Create a branch in the `taloo-database` repo:
   ```bash
   cd /path/to/taloo-database
   git checkout -b feature/add-new-table
   ```

2. Add your migration file to `supabase/migrations/`.

3. Commit, push, and open a PR against `master`.

4. Supabase automatically creates a preview database branch. Wait a minute for it to provision.

5. Get connection details from the Supabase dashboard (see "Switching Databases" above).

6. Switch your local backend to the preview branch:
   ```bash
   ./scripts/switch-db.sh preview <ref> <password>
   ```

7. Restart the backend and test your changes.

8. When satisfied, merge the PR. Supabase applies the migration to the main branch.

9. Switch back to main:
   ```bash
   ./scripts/switch-db.sh main
   ```

10. Delete the preview branch in the Supabase dashboard after merge (it is not cleaned up automatically).

## Seed Data

The file `taloo-database/supabase/seed.sql` runs automatically on preview branches to populate required reference data:

- **system schema** — Demo workspace, user profile, memberships, integrations
- **ontology schema** — Document types, attribute types

Uses fixed deterministic UUIDs and `ON CONFLICT DO NOTHING` so re-runs are safe. This ensures preview branches have enough data for the application to function.

## Schemas

The database uses three application schemas (plus `adk` for Google ADK session storage):

| Schema | Purpose | Example Tables |
|--------|---------|----------------|
| **`ats`** | Core recruitment data | `vacancies`, `candidates`, `applications`, `pre_screenings`, `candidate_documents`, `candidate_attributes`, `office_locations` |
| **`system`** | Multi-tenant infrastructure | `workspaces`, `user_profiles`, `memberships`, `integrations` |
| **`ontology`** | Type/reference data | `types_documents`, `types_attributes`, `types_sync_with` |

The app's `database.py` auto-creates these schemas on startup via `CREATE SCHEMA IF NOT EXISTS`. It also runs bootstrap migrations for tables that the application depends on (ADK session tables, document collection tables, etc.).

## Important Notes

- **Cloud Run** uses direct Supabase connections (`db.<ref>.supabase.co`). This works because GCP supports IPv6.
- **Local dev** must use the pooler connection (`aws-1-eu-west-1.pooler.supabase.com`). Direct connections fail due to IPv6.
- The **pooler password** differs from the **direct connection password** for the same project. Make sure you copy the right one from the Connection Pooler section.
- `database.py` runs `run_schema_migrations()` on startup, which creates schemas and bootstraps tables. This is a safety net — the source of truth for schema is the migration files in `taloo-database`.
- The connection pool is configured for Supabase Session Mode Pooler: `min_size=2`, `max_size=10`, `max_inactive_connection_lifetime=300s`, with a `SELECT 1` health check on acquire.
