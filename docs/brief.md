# Frontend Brief

## Pipeline nav — global candidacies view

### What changed on the backend
`GET /candidacies` (no `vacancy_id` param) now returns **all candidacies** workspace-wide — one entry per (candidate × vacancy) application. Previously it only returned talent-pool entries (`vacancy_id IS NULL`).

### Why
The old "Kandidaten" pipeline tab was broken: a candidate linked to multiple vacancies (e.g. Jan Peeters → 3 vacancies in 3 different stages) had to be placed in a single kanban column, which made no sense. Standard ATS practice (Greenhouse, Ashby, Lever) separates two concepts:

1. **Kandidaten** — the people database. A list of persons. No kanban.
2. **Pipeline** — the overview of all active applications by stage. One card per application, not one card per person.

### Required frontend changes

#### 1. Add a new top-level nav item: "Pipeline"
- Route: `/records/pipeline` (or similar)
- Calls `GET /candidacies?workspace_id=...` (no vacancy_id)
- Renders a **kanban grouped by stage** (same columns as today: Nieuw, Pre-screening, Gekwalificeerd, …)
- Each card shows: **candidate name** + **vacancy title** (the `vacancy.title` field in the response)
- Jan Peeters will appear as **3 separate cards** in 3 different columns — that's correct

#### 2. Remove the "Pipeline" tab from `/records/candidates`
- The Kandidaten page keeps only: **Lijst** and **Gearchiveerd** tabs
- It is now purely a candidate database — no kanban, no stage columns

### API response shape (unchanged)
Each candidacy card has:
```json
{
  "id": "...",
  "stage": "pre_screening",
  "candidate": { "full_name": "Jan Peeters", ... },
  "vacancy": { "title": "Logistiek Supervisor", ... },
  "linked_vacancies": [
    { "vacancy_title": "Customer Service Medewerker", "stage": "qualified" },
    { "vacancy_title": "Technisch commercieel bin...", "stage": "interview_planned" }
  ],
  ...
}
```
`linked_vacancies` now excludes the card's own vacancy (backend fix), so it can be shown as "also active in:" chips without duplication.

### No breaking changes
- `GET /candidacies?vacancy_id=XXX` — unchanged (per-vacancy pipeline, used inside vacancy detail if applicable)
- `GET /candidacies?candidate_id=XXX` — unchanged (candidate detail panel)
- Stage transitions (`PATCH /candidacies/{id}/stage`) — unchanged
