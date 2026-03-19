# Connexys → Taloo Vacancy Mapping

Voorbeeld vacature: **Festivalmedewerker eetkraam - ARBEIDER**

---

## Synchronisatie velden

| Label | Veldnaam | Waarde |
|---|---|---|
| Sync naar Taloo | `sync_to_taloo` | *(nieuw veld — moet nog ingevuld worden)* |
| ITZU Website | `cbx_itzu_website__c` | true → online pre-screening |

---

## Vacature gegevens

| Label | Veldnaam | Waarde |
|---|---|---|
| Vacaturenaam | `Name` | Festivalmedewerker eetkraam - ARBEIDER |
| Klant | `cxsrec__Account_name__c` | Beverly Food And Beverage Bv |
| Land | `cxsrec__Country__c` | Belgium |
| Locatie | `job_vdab_worklocation__c` | 3600 Genk |
| Soort contract | `cxsrec__Contract_type__c` | Studentenjobs |
| Sector | `job_sector__c` | Evenementen |
| Statuut | `job_section__c` | Arbeider |
| Taal | `job_language__c` | Nederlands |
| Werkregime | `job_work_regime__c` | Part-time |
| Brand | `job_brand__c` | ITZU |
| Startdatum | `cxsrec__Job_start_date__c` | 2025-01-15 |
| Aantal te werven | `cxsrec__Number_of_employees_to_be_hired__c` | 20 |

---

## Eigenaar & kantoor

| Label | Veldnaam | Waarde |
|---|---|---|
| Eigenaar (recruiter) | `Owner.Name` | HRL Admin |
| Eigenaar e-mail | `Owner.Email` | *(niet beschikbaar in sandbox testdata)* |
| Kantoor | `job_office__r.Name` | Bevers |
| Kantoor e-mail | `job_office__r.office_email__c` | horeca@itzu.eu |

---

## Vacatureteksten

| Label | Veldnaam | Waarde |
|---|---|---|
| Functieomschrijving | `cxsrec__Job_description__c` | *(zie hieronder)* |
| Functie-eisen | `cxsrec__Job_requirements__c` | *(zie hieronder)* |
| Arbeidsvoorwaarden | `cxsrec__Compensation_benefits__c` | *(zie hieronder)* |

### Functieomschrijving

Kun jij al niet meer wachten tot de events en festivals weer van start gaan? Altijd al gedroomd van werken in een gezellige eetstand en deel uitmaken van het team dat de meest heerlijke pasta's, pizza's en meer bereidt? Zoek niet verder, wij hebben de ideale baan voor jou!

- Bereiden en uitscheppen van snacks
- Bestellingen opnemen en afrekenen
- Zorgen dat de eetkraam er netjes blijft uitzien

### Functie-eisen

- Jij hebt oog voor **hygiëne** én **kwaliteit**
- Hoe meer je kan werken, hoe liever!
- Je bent je ervan bewust dat events en festivals zeer druk kunnen zijn en je geeft steeds 100% van jezelf!
- Al ervaring opgedaan in een eetkraam? Dat is zeker een pluspunt!
- **Teamwork** makes the dream work - jij werkt vlot samen met anderen
- Bij voorkeur ben je in het bezit van een eigen wagen
- Je begrijpt en spreekt vloeiend de **Nederlandse** taal

### Arbeidsvoorwaarden

- Werken op de leukste events/festivals in België
- Terechtkomen in een tof, geëngageerd team
- Verloning volgens barema (€14,3707)

---

## Logica

- **sync_to_taloo = true** → vacature wordt gesynchroniseerd naar Taloo
- **cbx_itzu_website = true** → pre-screening verloopt **online** (via Taloo)
- **cbx_itzu_website = false** → pre-screening verloopt **offline** (manueel op kantoor)
