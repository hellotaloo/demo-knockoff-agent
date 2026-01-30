"""Data Query Agent - Query Supabase data using natural language."""

import os
from google.adk.agents import Agent
from google.adk.tools import ToolContext
from typing import Optional
import asyncpg

# Reference to the database pool - will be set by app.py or created lazily
_db_pool: Optional[asyncpg.Pool] = None


def set_db_pool(pool: asyncpg.Pool):
    """Set the database connection pool reference."""
    global _db_pool
    _db_pool = pool


async def get_pool() -> asyncpg.Pool:
    """Get the database pool, creating one lazily if not initialized."""
    global _db_pool
    if _db_pool is None:
        # Lazily create pool if not set by app.py (e.g., when using adk web)
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL environment variable is required")
        # Convert SQLAlchemy URL to asyncpg format if needed
        raw_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        _db_pool = await asyncpg.create_pool(raw_url, min_size=1, max_size=5)
    return _db_pool


# ============================================================================
# Database Query Tools
# ============================================================================

async def query_vacancies(
    tool_context: ToolContext,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 10
) -> dict:
    """
    Query vacancies from the database with optional filters.
    
    Args:
        status: Filter by vacancy status (new, draft, screening_active, archived)
        search: Search in title, company, or location (case-insensitive)
        limit: Maximum number of results to return (default 10, max 50)
    
    Returns:
        Dictionary with vacancies list and total count
    """
    pool = await get_pool()
    
    # Cap limit at 50
    limit = min(limit, 50)
    
    # Build query with optional filters
    conditions = []
    params = []
    param_idx = 1
    
    if status:
        conditions.append(f"status = ${param_idx}")
        params.append(status)
        param_idx += 1
    
    if search:
        conditions.append(f"(title ILIKE ${param_idx} OR company ILIKE ${param_idx} OR location ILIKE ${param_idx})")
        params.append(f"%{search}%")
        param_idx += 1
    
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM vacancies {where_clause}"
    total = await pool.fetchval(count_query, *params)
    
    # Get vacancies
    query = f"""
        SELECT id, title, company, location, status, 
               created_at, source,
               (SELECT EXISTS(SELECT 1 FROM pre_screenings ps WHERE ps.vacancy_id = vacancies.id)) as has_screening
        FROM vacancies
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ${param_idx}
    """
    params.append(limit)
    
    rows = await pool.fetch(query, *params)
    
    vacancies = [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "company": row["company"],
            "location": row["location"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "source": row["source"],
            "has_screening": row["has_screening"]
        }
        for row in rows
    ]
    
    return {
        "vacancies": vacancies,
        "total": total,
        "returned": len(vacancies)
    }


async def query_applications(
    tool_context: ToolContext,
    vacancy_id: Optional[str] = None,
    qualified: Optional[bool] = None,
    completed: Optional[bool] = None,
    channel: Optional[str] = None,
    limit: int = 20
) -> dict:
    """
    Query applications from the database with optional filters.
    
    Args:
        vacancy_id: Filter by specific vacancy ID (UUID)
        qualified: Filter by qualification status (True/False)
        completed: Filter by completion status (True/False)
        channel: Filter by channel (voice, whatsapp)
        limit: Maximum number of results to return (default 20, max 100)
    
    Returns:
        Dictionary with applications list and total count
    """
    pool = await get_pool()
    
    import uuid as uuid_module
    
    # Cap limit at 100
    limit = min(limit, 100)
    
    # Build query with optional filters
    conditions = []
    params = []
    param_idx = 1
    
    if vacancy_id:
        try:
            vacancy_uuid = uuid_module.UUID(vacancy_id)
            conditions.append(f"a.vacancy_id = ${param_idx}")
            params.append(vacancy_uuid)
            param_idx += 1
        except ValueError:
            return {"error": f"Invalid vacancy_id format: {vacancy_id}"}
    
    if qualified is not None:
        conditions.append(f"a.qualified = ${param_idx}")
        params.append(qualified)
        param_idx += 1
    
    if completed is not None:
        conditions.append(f"a.completed = ${param_idx}")
        params.append(completed)
        param_idx += 1
    
    if channel:
        conditions.append(f"a.channel = ${param_idx}")
        params.append(channel)
        param_idx += 1
    
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM applications a {where_clause}"
    total = await pool.fetchval(count_query, *params)
    
    # Get applications with vacancy title
    query = f"""
        SELECT a.id, a.vacancy_id, v.title as vacancy_title,
               a.candidate_name, a.channel, a.completed, a.qualified,
               a.started_at, a.completed_at, a.interaction_seconds
        FROM applications a
        LEFT JOIN vacancies v ON a.vacancy_id = v.id
        {where_clause}
        ORDER BY a.started_at DESC
        LIMIT ${param_idx}
    """
    params.append(limit)
    
    rows = await pool.fetch(query, *params)
    
    applications = [
        {
            "id": str(row["id"]),
            "vacancy_id": str(row["vacancy_id"]),
            "vacancy_title": row["vacancy_title"],
            "candidate_name": row["candidate_name"],
            "channel": row["channel"],
            "completed": row["completed"],
            "qualified": row["qualified"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            "interaction_seconds": row["interaction_seconds"]
        }
        for row in rows
    ]
    
    return {
        "applications": applications,
        "total": total,
        "returned": len(applications)
    }


async def get_statistics(
    tool_context: ToolContext,
    vacancy_id: Optional[str] = None
) -> dict:
    """
    Get aggregated statistics for vacancies and applications.
    
    Args:
        vacancy_id: Optional vacancy ID to get stats for a specific vacancy.
                   If not provided, returns overall statistics.
    
    Returns:
        Dictionary with statistics including totals, rates, and breakdowns
    """
    pool = await get_pool()
    
    import uuid as uuid_module
    
    if vacancy_id:
        # Stats for specific vacancy
        try:
            vacancy_uuid = uuid_module.UUID(vacancy_id)
        except ValueError:
            return {"error": f"Invalid vacancy_id format: {vacancy_id}"}
        
        # Get vacancy info
        vacancy = await pool.fetchrow(
            "SELECT title, company, status FROM vacancies WHERE id = $1",
            vacancy_uuid
        )
        if not vacancy:
            return {"error": "Vacancy not found"}
        
        # Get application stats
        stats = await pool.fetchrow("""
            SELECT 
                COUNT(*) as total_applications,
                COUNT(*) FILTER (WHERE completed = true) as completed,
                COUNT(*) FILTER (WHERE qualified = true) as qualified,
                COUNT(*) FILTER (WHERE channel = 'voice') as voice_count,
                COUNT(*) FILTER (WHERE channel = 'whatsapp') as whatsapp_count,
                COALESCE(AVG(interaction_seconds), 0) as avg_interaction_seconds,
                MAX(started_at) as last_application_at
            FROM applications
            WHERE vacancy_id = $1
        """, vacancy_uuid)
        
        total = stats["total_applications"]
        completed = stats["completed"]
        
        return {
            "vacancy": {
                "id": vacancy_id,
                "title": vacancy["title"],
                "company": vacancy["company"],
                "status": vacancy["status"]
            },
            "total_applications": total,
            "completed": completed,
            "completion_rate": round((completed / total * 100) if total > 0 else 0, 1),
            "qualified": stats["qualified"],
            "qualification_rate": round((stats["qualified"] / completed * 100) if completed > 0 else 0, 1),
            "channel_breakdown": {
                "voice": stats["voice_count"],
                "whatsapp": stats["whatsapp_count"]
            },
            "avg_interaction_seconds": round(stats["avg_interaction_seconds"]),
            "last_application_at": stats["last_application_at"].isoformat() if stats["last_application_at"] else None
        }
    
    else:
        # Overall statistics
        vacancy_stats = await pool.fetchrow("""
            SELECT 
                COUNT(*) as total_vacancies,
                COUNT(*) FILTER (WHERE status = 'new') as new_count,
                COUNT(*) FILTER (WHERE status = 'draft') as draft_count,
                COUNT(*) FILTER (WHERE status = 'screening_active') as screening_active_count,
                COUNT(*) FILTER (WHERE status = 'archived') as archived_count,
                (SELECT COUNT(*) FROM pre_screenings) as with_screening
            FROM vacancies
        """)
        
        app_stats = await pool.fetchrow("""
            SELECT 
                COUNT(*) as total_applications,
                COUNT(*) FILTER (WHERE completed = true) as completed,
                COUNT(*) FILTER (WHERE qualified = true) as qualified,
                COUNT(*) FILTER (WHERE channel = 'voice') as voice_count,
                COUNT(*) FILTER (WHERE channel = 'whatsapp') as whatsapp_count,
                COALESCE(AVG(interaction_seconds), 0) as avg_interaction_seconds
            FROM applications
        """)
        
        total_apps = app_stats["total_applications"]
        completed = app_stats["completed"]
        
        return {
            "vacancies": {
                "total": vacancy_stats["total_vacancies"],
                "by_status": {
                    "new": vacancy_stats["new_count"],
                    "draft": vacancy_stats["draft_count"],
                    "screening_active": vacancy_stats["screening_active_count"],
                    "archived": vacancy_stats["archived_count"]
                },
                "with_screening": vacancy_stats["with_screening"]
            },
            "applications": {
                "total": total_apps,
                "completed": completed,
                "completion_rate": round((completed / total_apps * 100) if total_apps > 0 else 0, 1),
                "qualified": app_stats["qualified"],
                "qualification_rate": round((app_stats["qualified"] / completed * 100) if completed > 0 else 0, 1),
                "by_channel": {
                    "voice": app_stats["voice_count"],
                    "whatsapp": app_stats["whatsapp_count"]
                },
                "avg_interaction_seconds": round(app_stats["avg_interaction_seconds"])
            }
        }


async def execute_analytics_query(
    tool_context: ToolContext,
    query_type: str,
    time_period: Optional[str] = None
) -> dict:
    """
    Execute predefined analytics queries for common insights.
    
    Args:
        query_type: Type of analytics query. Options:
            - "top_vacancies": Top vacancies by application count
            - "recent_applications": Most recent applications
            - "daily_summary": Applications per day (requires time_period)
            - "channel_performance": Comparison of voice vs whatsapp performance
            - "qualification_trends": Qualification rates over time
        time_period: Time filter like "today", "week", "month" (for daily_summary)
    
    Returns:
        Dictionary with the analytics results
    """
    pool = await get_pool()
    
    if query_type == "top_vacancies":
        rows = await pool.fetch("""
            SELECT v.id, v.title, v.company, 
                   COUNT(a.id) as application_count,
                   COUNT(a.id) FILTER (WHERE a.qualified = true) as qualified_count
            FROM vacancies v
            LEFT JOIN applications a ON v.id = a.vacancy_id
            GROUP BY v.id, v.title, v.company
            ORDER BY application_count DESC
            LIMIT 10
        """)
        
        return {
            "query": "top_vacancies",
            "results": [
                {
                    "vacancy_id": str(row["id"]),
                    "title": row["title"],
                    "company": row["company"],
                    "application_count": row["application_count"],
                    "qualified_count": row["qualified_count"]
                }
                for row in rows
            ]
        }
    
    elif query_type == "recent_applications":
        rows = await pool.fetch("""
            SELECT a.id, a.candidate_name, a.channel, a.completed, a.qualified,
                   a.started_at, v.title as vacancy_title
            FROM applications a
            LEFT JOIN vacancies v ON a.vacancy_id = v.id
            ORDER BY a.started_at DESC
            LIMIT 20
        """)
        
        return {
            "query": "recent_applications",
            "results": [
                {
                    "application_id": str(row["id"]),
                    "candidate_name": row["candidate_name"],
                    "vacancy_title": row["vacancy_title"],
                    "channel": row["channel"],
                    "completed": row["completed"],
                    "qualified": row["qualified"],
                    "started_at": row["started_at"].isoformat() if row["started_at"] else None
                }
                for row in rows
            ]
        }
    
    elif query_type == "daily_summary":
        # Default to last 7 days
        days = 7
        if time_period == "today":
            days = 1
        elif time_period == "week":
            days = 7
        elif time_period == "month":
            days = 30
        
        rows = await pool.fetch(f"""
            SELECT DATE(started_at) as date,
                   COUNT(*) as total,
                   COUNT(*) FILTER (WHERE completed = true) as completed,
                   COUNT(*) FILTER (WHERE qualified = true) as qualified
            FROM applications
            WHERE started_at >= CURRENT_DATE - INTERVAL '{days} days'
            GROUP BY DATE(started_at)
            ORDER BY date DESC
        """)
        
        return {
            "query": "daily_summary",
            "period": time_period or "week",
            "results": [
                {
                    "date": row["date"].isoformat() if row["date"] else None,
                    "total": row["total"],
                    "completed": row["completed"],
                    "qualified": row["qualified"]
                }
                for row in rows
            ]
        }
    
    elif query_type == "channel_performance":
        rows = await pool.fetch("""
            SELECT channel,
                   COUNT(*) as total,
                   COUNT(*) FILTER (WHERE completed = true) as completed,
                   COUNT(*) FILTER (WHERE qualified = true) as qualified,
                   COALESCE(AVG(interaction_seconds), 0) as avg_seconds
            FROM applications
            GROUP BY channel
        """)
        
        return {
            "query": "channel_performance",
            "results": [
                {
                    "channel": row["channel"],
                    "total": row["total"],
                    "completed": row["completed"],
                    "qualified": row["qualified"],
                    "completion_rate": round((row["completed"] / row["total"] * 100) if row["total"] > 0 else 0, 1),
                    "qualification_rate": round((row["qualified"] / row["completed"] * 100) if row["completed"] > 0 else 0, 1),
                    "avg_interaction_seconds": round(row["avg_seconds"])
                }
                for row in rows
            ]
        }
    
    elif query_type == "qualification_trends":
        rows = await pool.fetch("""
            SELECT DATE(started_at) as date,
                   COUNT(*) FILTER (WHERE completed = true) as completed,
                   COUNT(*) FILTER (WHERE qualified = true) as qualified
            FROM applications
            WHERE started_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY DATE(started_at)
            HAVING COUNT(*) FILTER (WHERE completed = true) > 0
            ORDER BY date DESC
        """)
        
        return {
            "query": "qualification_trends",
            "results": [
                {
                    "date": row["date"].isoformat() if row["date"] else None,
                    "completed": row["completed"],
                    "qualified": row["qualified"],
                    "qualification_rate": round((row["qualified"] / row["completed"] * 100) if row["completed"] > 0 else 0, 1)
                }
                for row in rows
            ]
        }
    
    else:
        return {
            "error": f"Unknown query_type: {query_type}",
            "available_types": [
                "top_vacancies",
                "recent_applications", 
                "daily_summary",
                "channel_performance",
                "qualification_trends"
            ]
        }


# ============================================================================
# Agent Definition
# ============================================================================

instruction = """Je bent een data-analist assistent voor Taloo, een recruitment platform. 
Je helpt gebruikers vragen te beantwoorden over vacatures, sollicitaties en statistieken in de database.

## TAAL
Je antwoordt ALTIJD in het Nederlands (Vlaams nl-BE), ongeacht de taal van de vraag.

## DATABASE SCHEMA
Je hebt toegang tot de volgende tabellen:

### vacancies (vacatures)
- id: UUID - unieke identifier
- title: titel van de vacature
- company: bedrijfsnaam
- location: locatie
- status: new (nieuw), draft (in opzet), screening_active (screening actief), archived (gearchiveerd)
- created_at: aanmaakdatum
- source: bron (salesforce, bullhorn, manual)
- has_screening: boolean - of er een pre-screening geconfigureerd is

### applications (sollicitaties)
- id: UUID - unieke identifier
- vacancy_id: verwijzing naar vacature
- candidate_name: naam van de kandidaat
- channel: voice of whatsapp
- completed: boolean - of het interview is afgerond
- qualified: boolean - of de kandidaat is gekwalificeerd
- started_at: starttijd
- completed_at: eindtijd
- interaction_seconds: duur van de interactie

### application_answers (antwoorden)
- application_id: verwijzing naar sollicitatie
- question_id: vraag ID (ko_1, qual_2, etc.)
- question_text: de gestelde vraag
- answer: het antwoord van de kandidaat
- passed: boolean - of de kandidaat slaagde voor deze vraag

## BESCHIKBARE TOOLS

1. **query_vacancies**: Zoek vacatures met filters (status, zoekterm, limiet)
2. **query_applications**: Zoek sollicitaties met filters (vacancy_id, qualified, completed, channel)
3. **get_statistics**: Haal statistieken op (algemeen of per vacature)
4. **execute_analytics_query**: Voer voorgedefinieerde analytische queries uit:
   - top_vacancies: Top vacatures op basis van aantal sollicitaties
   - recent_applications: Meest recente sollicitaties
   - daily_summary: Dagelijkse samenvatting (met time_period: today/week/month)
   - channel_performance: Vergelijking voice vs whatsapp
   - qualification_trends: Kwalificatietrends over tijd

## RICHTLIJNEN

1. **Begrijp de vraag**: Analyseer wat de gebruiker wil weten
2. **Kies de juiste tool**: Gebruik de meest geschikte tool voor de vraag
3. **Interpreteer resultaten**: Geef een duidelijke, menselijke samenvatting
4. **Wees specifiek**: Noem concrete cijfers en percentages
5. **Wees beknopt**: Geef een helder antwoord zonder overbodige informatie

## VOORBEELDEN

**Vraag**: "Hoeveel sollicitaties zijn er vandaag?"
**Actie**: Gebruik execute_analytics_query met query_type="daily_summary" en time_period="today"

**Vraag**: "Wat is de kwalificatieratio voor de laatste vacature?"
**Actie**: Eerst query_vacancies om de laatste vacature te vinden, dan get_statistics met dat vacancy_id

**Vraag**: "Toon me alle gekwalificeerde kandidaten"
**Actie**: Gebruik query_applications met qualified=True

**Vraag**: "Hoe presteert WhatsApp vergeleken met voice?"
**Actie**: Gebruik execute_analytics_query met query_type="channel_performance"

## RESPONSE FORMAAT
- Geef altijd een directe samenvatting
- Gebruik opsommingen voor meerdere items
- Toon percentages met 1 decimaal
- Vermeld relevante context (bijv. "van de 50 totale sollicitaties")
"""

root_agent = Agent(
    name="data_analist",
    model="gemini-2.5-flash",
    instruction=instruction,
    description="Data analist die vacatures, sollicitaties en statistieken ophaalt uit de database",
    tools=[
        query_vacancies,
        query_applications,
        get_statistics,
        execute_analytics_query
    ],
)
