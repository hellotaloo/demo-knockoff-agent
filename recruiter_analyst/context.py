"""Company context templates for the Recruiter Analyst Agent."""

# Taloo platform context - always included
TALOO_CONTEXT = """
## TALOO PLATFORM
Taloo is een AI-powered recruitment platform voor blue-collar vacatures in België en Nederland.

### Kanalen
- **WhatsApp**: Asynchrone screening via chat
- **Voice**: Telefonische screening met AI

### Focus Sectoren
- Productie & Industrie
- Logistiek & Transport
- Retail & Verkoop
- Horeca & Catering
- Bouw & Techniek

### Interview Structuur
1. **Knockout vragen** (harde eisen):
   - Werkvergunning België (verplicht)
   - Beschikbaarheid (voltijd/deeltijd, starttermijn)
   - Fysieke geschiktheid (tillen, staan, ploegen)
   - Vervoer (rijbewijs, eigen vervoer, bereikbaarheid)

2. **Kwalificatievragen** (zachte criteria):
   - Relevante werkervaring
   - Technische vaardigheden
   - Motivatie voor de functie
   - Teamwork & communicatie

### Metrics
- **Completion rate**: % kandidaten die het interview afmaken
- **Qualification rate**: % afgeronde interviews waar kandidaat gekwalificeerd is
- **Interaction time**: Gemiddelde duur van het interview
"""

# Placeholder for client-specific context
DEFAULT_CLIENT_CONTEXT = """
## KLANT CONTEXT
Geen specifieke klantcontext geconfigureerd.

Om klantspecifieke context toe te voegen:
1. Bedrijfsinformatie (naam, sector, cultuur)
2. Specifieke hiring requirements
3. Interne processen en SLA's
4. Voorkeuren en prioriteiten
"""


def get_full_context(client_context: str = None) -> str:
    """
    Get the full context for the analyst agent.
    
    Args:
        client_context: Optional client-specific context to include
    
    Returns:
        Combined context string
    """
    client = client_context if client_context else DEFAULT_CLIENT_CONTEXT
    return f"{TALOO_CONTEXT}\n{client}"


# Recruitment best practices for strategy advice
RECRUITMENT_BEST_PRACTICES = """
## RECRUITMENT BEST PRACTICES

### Verbeteren van Completion Rate
- Kortere interviews (max 5-7 vragen totaal)
- Duidelijke introductie met verwachte duur
- Vriendelijke, informele toon
- Snelle knockout om tijd te besparen

### Verbeteren van Qualification Rate
- Duidelijke vacaturetekst met realistische eisen
- Knockout vragen eerst om snel te filteren
- Balans tussen strikte en flexibele criteria
- Review knockout criteria regelmatig

### Kanaal Optimalisatie
- **WhatsApp**: Beter voor jongere doelgroep, flexibele timing
- **Voice**: Beter voor directe interactie, hogere engagement

### Prioriteren van Kandidaten
1. Gekwalificeerd + korte interactietijd = efficiënte kandidaat
2. Alle knockout vragen gepasseerd = voldoet aan harde eisen
3. Positieve antwoorden op kwalificatievragen = goede match

### Vacancy Optimalisatie
- Specifieke, realistische functietitel
- Duidelijke locatie en bereikbaarheid
- Eerlijke beschrijving van werkomstandigheden
- Aantrekkelijke arbeidsvoorwaarden benadrukken
"""
