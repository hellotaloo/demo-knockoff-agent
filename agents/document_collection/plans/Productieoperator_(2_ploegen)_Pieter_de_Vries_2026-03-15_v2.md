# Collection Plan v2: Pieter de Vries × Productieoperator (2 ploegen)

**Generated:** 2026-03-15 (v2 — simplified planner)
**Vacancy:** Productieoperator (2 ploegen) @ Klant regio Diest
**Candidate:** Pieter de Vries (nieuwe kandidaat — geen bestaand dossier)
**Start date:** 2026-03-16 (nog 1 dag)
**Regime:** full (voltijds)
**Candidacy stage:** offer

## Summary
De startdatum nadert snel — binnen 1 dag! Ik zal de benodigde documenten en gegevens verzamelen voor Pieter de Vries, een nieuwe kandidaat. Dit omvat 3 aanbevolen documenten (VCA, diploma, CV) en 8 essentiële attributen. Daarnaast zal ik een medisch onderzoek inplannen en het contract ter ondertekening aanbieden.

---

## Documents to Collect (3)

| # | Slug | Name | Priority | Scan Mode | Reason |
|---|------|------|----------|-----------|--------|
| 1 | `prato_1` | Basisveiligheid VCA | recommended | single | Industrie met veiligheidsrisico's |
| 2 | `diploma` | Diploma/Certificaat | recommended | single | Technische achtergrond staven |
| 3 | `cv` | CV / Curriculum Vitae | recommended | single | Handig voor het dossier |

## Attributes to Collect (8)

| # | Slug | Name | Method | Priority | Reason |
|---|------|------|--------|----------|--------|
| 1 | `date_of_birth` | Geboortedatum | document | required | Administratie + contract |
| 2 | `marital_status` | Burgerlijke staat | ask | required | Dimona + contract |
| 3 | `nationality` | Nationaliteit | document | required | Arbeidstoegang bepalen |
| 4 | `iban` | Bankrekeningnummer | ask | required | Loonuitbetaling |
| 5 | `national_register_nr` | Rijksregisternummer | document | required | Administratie + contract |
| 6 | `emergency_contact` | Noodcontact | ask | required | Veiligheid + noodgevallen |
| 7 | `work_eligibility` | Arbeidstoegang België | document | required | Wettelijke vereiste |
| 8 | `has_own_transport` | Eigen vervoer | ask | recommended | Ploegwerk + locatie Diest |

**Ask attributes (conversation):** marital_status, iban, emergency_contact, has_own_transport
**Document attributes (auto-extracted):** date_of_birth, nationality, national_register_nr, work_eligibility

## Agent Managed Tasks (1)

| # | Slug | Action |
|---|------|--------|
| 1 | `medical_screening` | Medisch onderzoek inplannen. Risico's: 1,1,1-trichloorethaan, Acetonitril, Acrylpolymeren. |

## Final Step
`contract_signing` — Contract ter ondertekening via Yousign (regime: full)

## Already Complete
(geen)

---

## Hardcoded by Agent (not in planner output)

These workflows are always handled by the collection agent, never by the planner:

### Identity & Work Permit Flow
1. Identity group: `id_card` (front+back) / `passport` (single) — agent asks for one
2. Work permit group: `prato_5` / `prato_101` / `prato_102` / `prato_9` / `prato_20` — auto-skipped for EU citizens

### Address Flow
1. `domicile_address` — Domicilie adres (always asked)
2. `adres_gelijk_aan_domicilie` — Verblijfsadres gelijk aan domicilie? (always asked)
3. `verblijfs_adres` — Verblijfsadres (only if different from domicile)

## Changes from v1
- Identity documents (id_card, passport) removed from planner output → hardcoded in agent
- Work permit documents (prato_5, prato_9, prato_20, prato_101, prato_102) removed from planner output → hardcoded in agent
- Address attributes removed from planner output → hardcoded in agent
- Planner now only outputs job-specific, variable documents (3 instead of 10)
- CLI auto-detects regime from placement table
