# Connexys / Salesforce API Overview

## Authentication

OAuth2 client_credentials flow against the Salesforce instance.

```
POST https://<instance>.my.salesforce.com/services/oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
client_id=<consumer_key>
client_secret=<consumer_secret>
```

Returns `access_token` and `instance_url`. All subsequent API calls use:
```
Authorization: Bearer <access_token>
```

## API Endpoint

```
GET https://<instance_url>/services/data/v62.0/query?q=<SOQL>
```

Pagination: max 2000 records per response. If `done: false`, follow `nextRecordsUrl` until `done: true`.

---

## Vacancy Object: `cxsrec__cxsPosition__c`

### SOQL Query

```sql
SELECT Id, Name, cxsrec__Status__c,
       cxsrec__Account__c, cxsrec__Account_name__c,
       cxsrec__Job_description__c,
       cxsrec__Job_requirements__c,
       cxsrec__Compensation_benefits__c,
       cxsrec__Country__c, cxsrec__Contract_type__c,
       job_vdab_worklocation__c, job_sector__c,
       job_section__c, job_language__c,
       job_work_regime__c, job_brand__c,
       cxsrec__Job_start_date__c,
       cxsrec__Number_of_employees_to_be_hired__c,
       Owner.Email, Owner.Name,
       job_office__r.office_email__c, job_office__r.Name,
       CreatedDate, LastModifiedDate
FROM cxsrec__cxsPosition__c
ORDER BY CreatedDate DESC
```

### Field Mapping

| Connexys Field | Label (NL) | Type | Example Value |
|---|---|---|---|
| `Id` | Record-ID | id (18) | `a0w9K000004EgTWQA0` |
| `Name` | Vacaturenaam | string (80) | Festivalmedewerker eetkraam - ARBEIDER |
| `cxsrec__Status__c` | Status | picklist | Nieuwe |
| `cxsrec__Account__c` | Klant | lookup (Account) | `0019K00000l7B44QAE` |
| `cxsrec__Account_name__c` | Naam van de organisatie | formula (string) | Beverly Food And Beverage Bv |
| `cxsrec__Job_description__c` | Functieomschrijving | html (131072) | Rich text HTML |
| `cxsrec__Job_requirements__c` | Functie-eisen | html (6000) | Rich text HTML |
| `cxsrec__Compensation_benefits__c` | Arbeidsvoorwaarden | html (6000) | Rich text HTML |
| `cxsrec__Country__c` | Land | picklist | Belgium |
| `cxsrec__Contract_type__c` | Soort contract | picklist | Studentenjobs |
| `job_vdab_worklocation__c` | Locatie | picklist (restricted) | 3600 Genk |
| `job_sector__c` | Sector | picklist (restricted) | Evenementen |
| `job_section__c` | Statuut | picklist (restricted) | Arbeider |
| `job_language__c` | Taal | picklist (restricted) | Nederlands |
| `job_work_regime__c` | Werkregime | picklist (restricted) | Part-time |
| `job_brand__c` | Brand | picklist (restricted) | ITZU |
| `cxsrec__Job_start_date__c` | Startdatum inzet | date | 2025-01-15 |
| `cxsrec__Number_of_employees_to_be_hired__c` | Aantal te werven medewerkers | double (3,0) | 20 |
| `Owner.Email` | Eigenaar e-mail | relationship (User) | jan.vandamme@itzu.eu |
| `Owner.Name` | Eigenaar naam | relationship (User) | Jan Van Damme |
| `job_office__r.office_email__c` | Kantoor e-mail | relationship (Office__c) | horeca@itzu.eu |
| `job_office__r.Name` | Kantoornaam | relationship (Office__c) | Bevers |
| `CreatedDate` | Aanmaakdatum | datetime | 2025-01-15T12:27:54.000+0000 |
| `LastModifiedDate` | Datum van laatste wijziging | datetime | 2025-09-25T12:37:32.000+0000 |

### Status Values (from UI tabs)

| Status | Sync? | Notes |
|---|---|---|
| Nieuwe | Yes | New vacancy |
| Instroomvacature | Yes | Intake vacancy |
| On hold | Yes | Paused |
| Ingevuld (ITZU) | Yes | Filled by ITZU |
| Ingevuld (klant) | Yes | Filled by client |
| Ingevuld (concurrent) | Yes | Filled by competitor |
| Heropend | Yes | Reopened |
| Gesloten | No | Closed |
| Bestelling ingetrokken | No | Order withdrawn |

### Notes

- `cxsrec__` prefix = Connexys managed package fields
- `job_*` fields (no prefix) = custom fields added by ITZU
- `cxsrec__Account_name__c` is a formula field — gives client name without needing a relationship query
- Rich text fields return raw HTML

---

## Test Results (Sandbox, 2026-03-19)

Instance: `connexys-5051--itzudev.sandbox.my.salesforce.com`
Total records: 5

| # | Name | Status | Client | Owner | Office (email) |
|---|---|---|---|---|---|
| 1 | Inschrijving Payroll Klant X | Nieuwe | Itzu Jobs2 Nv | Jan Van Damme (jan.vandamme@itzu.eu) | Hoofdkantoor (talentrecruitment@itzu.eu) |
| 2 | Inschrijving Kantoor Construct/VCU Vlaanderen | Nieuwe | Itzu Nv | Jan Van Damme (jan.vandamme@itzu.eu) | Construct/VCU Vlaanderen KMO (—) |
| 3 | Inschrijving Kantoor Bevers | Nieuwe | Itzu Nv | Jan Van Damme (jan.vandamme@itzu.eu) | Bevers (horeca@itzu.eu) |
| 4 | Inschrijving Kantoor Antwerpen Industrie | Nieuwe | Itzu Nv | Jan Van Damme (jan.vandamme@itzu.eu) | Antwerpen Industrie (antwerpen@itzu.eu) |
| 5 | Bediening Bakkerij | Nieuwe | ITZU Nederland | Morena Castro (morena.castro@itzu.eu) | Genk (frontoffice@itzu.eu) |

---

## Related Objects (for future use)

| Object | API Name | Relationship to Vacancy |
|---|---|---|
| Application | `cxsrec__cxsJob_application__c` | Child via `cxsrec__Position__c` |
| Candidate | `cxsrec__cxsCandidate__c` | Via Application |
| Account (Client) | `Account` | Parent via `cxsrec__Account__c` |
| Contact | `Contact` | Recruiter, Hiring Manager lookups |
| Placement | `cxsrec__Placement__c` | Child via `Job__c` |

### Key Relationships on Vacancy

| Field | Points To | Label |
|---|---|---|
| `cxsrec__Account__c` | Account | Klant |
| `cxsrec__Recruiter__c` | Contact | Recruiter |
| `cxsrec__Hiringmanager__c` | Contact | Hiring manager |
| `Contact__c` | Contact | Contact klant |
| `job_office__c` | Office__c | Kantoor |

### Child Relationships

| Relationship | Child Object | Use |
|---|---|---|
| `cxsrec__Job_applications__r` | `cxsrec__cxsJob_application__c` | Applications/Sollicitaties |
| `Placements__r` | `cxsrec__Placement__c` | Placements |
| `cxsrec__Hard_criteria__r` | `cxsrec__cxsHard_criterium__c` | Hard criteria |
