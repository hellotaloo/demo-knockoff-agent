# Collection Plan v3: Pieter de Vries × Productieoperator (2 ploegen)

**Generated:** 2026-03-15 (v3 — conversation_flow format)
**Vacancy:** Productieoperator (2 ploegen) @ Klant regio Diest
**Candidate:** Pieter de Vries (nieuwe kandidaat — geen bestaand dossier)
**Start date:** 2026-03-29 (nog 14 dagen)
**Regime:** full (voltijds)
**Candidacy stage:** offer

## Summary
Ik zal Pieter de Vries, een nieuwe kandidaat voor de functie van Productieoperator, begeleiden bij het verzamelen van de benodigde documenten en gegevens. Het plan omvat 8 stappen, inclusief identiteitscontrole, adresgegevens, persoonsgegevens, aanvullende documenten, het inplannen van een medisch onderzoek en het aanbieden van het contract. Met nog 14 dagen tot de startdatum is er voldoende tijd, maar een vlotte afhandeling is gewenst.

---

## Verification Flags

| Flag | Needed | Reason |
|------|--------|--------|
| Identity verification | Yes | Nieuwe kandidaat, geen identiteitsdocument op dossier |
| Work eligibility | Yes | Arbeidstoegang moet worden vastgesteld |
| Address | Yes | Geen adresgegevens op dossier |

## Conversation Flow (8 steps)

| Step | Type | Description | Requires | Items |
|------|------|-------------|----------|-------|
| 1 | `greeting_and_consent` | Begroeting en toestemming vragen | — | — |
| 2 | `identity_verification` | Identiteitsdocument verzamelen | — | Agent bepaalt (ID-kaart/paspoort + werkvergunning indien nodig) |
| 3 | `address_collection` | Adresgegevens verzamelen | — | Agent bepaalt (domicilie → gelijk_aan → verblijfs) |
| 4 | `collect_attributes` | Persoonsgegevens opvragen | — | 4 items (zie onder) |
| 5 | `collect_documents` | Aanvullende documenten | — | 3 items (zie onder) |
| 6 | `medical_screening` | Medisch onderzoek inplannen | `identity_verification` | Risico's: trichloorethaan, acetonitril, acrylpolymeren |
| 7 | `contract_signing` | Contract ter ondertekening | `identity_verification`, `address_collection`, `collect_attributes` | — |
| 8 | `closing` | Samenvatting en afsluiting | — | — |

### Step 4: Collect Attributes

| # | Slug | Method | Priority | Reason |
|---|------|--------|----------|--------|
| 1 | `has_own_transport` | ask | recommended | Ploegwerk, bereikbaarheid |
| 2 | `marital_status` | ask | required | Dimona + contract |
| 3 | `iban` | ask | required | Loonuitbetaling |
| 4 | `emergency_contact` | ask | required | Noodgevallen |

### Step 5: Collect Documents

| # | Slug | Priority | Reason |
|---|------|----------|--------|
| 1 | `prato_1` (VCA) | recommended | Industrie + veiligheidsrisico's |
| 2 | `diploma` | recommended | Technische achtergrond |
| 3 | `cv` | recommended | Compleet dossier |

## Attributes from Documents (auto-extracted)

| Slug | Reason |
|------|--------|
| `date_of_birth` | Van identiteitsdocument |
| `nationality` | Van identiteitsdocument |
| `national_register_nr` | Van identiteitsdocument |
| `work_eligibility` | Afgeleid uit identiteitsdocument + nationaliteit |

## Already Known
- Documents: (geen)
- Attributes: (geen)

---

## Changes from v2
- Output is now `conversation_flow` with ordered steps instead of flat lists
- Each step has a `type` and optional `requires` conditions
- Items only contain slugs — no baked-in field definitions or metadata
- Agent loads type definitions dynamically from DB at runtime
- `context` block includes `candidacy_stage` and `candidacy_context`
- Planner no longer enriches output with scan_mode, verification_config, fields
