# Collection Plan: Pieter de Vries × Productieoperator (2 ploegen)

**Generated:** 2026-03-15
**Vacancy:** Productieoperator (2 ploegen) @ Klant regio Diest
**Candidate:** Pieter de Vries (nieuwe kandidaat — geen bestaand dossier)
**Start date:** 2026-03-16 (nog 1 dag)
**Regime:** full (voltijds)
**Candidacy stage:** offer

## Summary
Dit is een nieuwe kandidaat, Pieter de Vries, voor de vacature Productieoperator. De startdatum nadert snel — binnen 1 dag. Ik zal 2 tot 5 documenten verzamelen (identiteitsbewijs, eventueel werkvergunning, VCA, diploma en CV) en 8 essentiële gegevens opvragen. Het systeem zal een medisch onderzoek inplannen en het contract ter ondertekening aanbieden.

---

## Documents to Collect (10)

| # | Slug | Name | Priority | Scan Mode | Reason |
|---|------|------|----------|-----------|--------|
| 1 | `id_card` | ID-kaart | conditional | front_back | Identiteitsbewijs EU/EER-burgers |
| 2 | `passport` | Paspoort | conditional | single | Vereist voor niet-EU/EER, of als EU-burger geen ID-kaart heeft |
| 3 | `prato_5` | Werkvergunning | conditional | single | Bewijs arbeidstoegang niet-EU/EER |
| 4 | `prato_101` | Verblijfsdocument - vrijstelling | conditional | single | Onbeperkte arbeidsmarkttoegang niet-EU/EER |
| 5 | `prato_102` | Verblijfsdocument - bijkomstig | conditional | single | Beperkte arbeidsmarkttoegang niet-EU/EER |
| 6 | `prato_9` | Vrijstelling arbeidskaart | conditional | single | Vrijgesteld van arbeidsvergunning |
| 7 | `prato_20` | Arbeidskaart | conditional | single | Oud systeem, nog geldig |
| 8 | `prato_1` | Basisveiligheid VCA | recommended | single | Industrie met veiligheidsrisico's |
| 9 | `diploma` | Diploma/Certificaat | recommended | single | Technische achtergrond vereist |
| 10 | `cv` | CV / Curriculum Vitae | recommended | single | Handig voor het dossier |

**Realistic scenario:** 1-2 verplichte docs (ID of paspoort + eventueel werkvergunning) + 3 aanbevolen

## Attributes to Collect (8)

| # | Slug | Name | Method | Priority | Reason |
|---|------|------|--------|----------|--------|
| 1 | `date_of_birth` | Geboortedatum | document | required | Administratie + Dimona |
| 2 | `marital_status` | Burgerlijke staat | ask | required | Dimona + contract |
| 3 | `nationality` | Nationaliteit | document | required | Arbeidstoegang bepalen |
| 4 | `iban` | Bankrekeningnummer | ask | required | Loonuitbetaling |
| 5 | `national_register_nr` | Rijksregisternummer | document | required | Administratie + Dimona |
| 6 | `emergency_contact` | Noodcontact | ask | required | Veiligheid. Fields: name, phone |
| 7 | `work_eligibility` | Arbeidstoegang België | document | required | Wettelijke vereiste |
| 8 | `has_own_transport` | Eigen vervoer | ask | recommended | 2-ploegen + locatie Diest |

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
These are always handled by the collection agent, never by the planner:
- `domicile_address` — Domicilie adres
- `adres_gelijk_aan_domicilie` — Verblijfsadres gelijk aan domicilie?
- `verblijfs_adres` — Verblijfsadres (only if different from domicile)

## Observations
- No address attributes in plan (correctly excluded by planner instruction)
- `collected_by` no longer influences the plan — all `is_default` attributes appear because candidate has empty dossier
- `marital_status` now correctly included (was skipped in previous run without regime)
- `final_step` = `contract_signing` because regime is "full"
- All prato work permit variants included as conditional (nationality unknown)
- `has_own_transport` included as recommended (2-ploegen + Diest location — good reasoning by planner)
