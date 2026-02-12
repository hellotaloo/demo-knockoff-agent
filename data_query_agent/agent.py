"""Data Query Agent - Smart Text-to-SQL agent for Taloo recruitment data."""

import os
import re
import asyncio
from google.adk.agents import Agent
from google.adk.tools import ToolContext
from typing import Optional
import asyncpg

# Reference to the database pool - will be set by app.py or created lazily
_db_pool: Optional[asyncpg.Pool] = None

# SQL query timeout in seconds
SQL_QUERY_TIMEOUT = 10
# Maximum rows to return
SQL_MAX_ROWS = 100


def set_db_pool(pool: asyncpg.Pool):
    """Set the database connection pool reference."""
    global _db_pool
    _db_pool = pool


async def get_pool() -> asyncpg.Pool:
    """Get the database pool, creating one lazily if not initialized."""
    global _db_pool
    if _db_pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL environment variable is required")
        raw_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        _db_pool = await asyncpg.create_pool(raw_url, min_size=1, max_size=5, statement_cache_size=0)
    return _db_pool


# ============================================================================
# Schema Discovery Tools
# ============================================================================

async def discover_tables(tool_context: ToolContext) -> dict:
    """
    Discover all available tables in the database.

    Call this FIRST to understand what data is available before writing queries.
    Returns tables from the 'ats' schema (main business data).

    Returns:
        Dictionary with table names and their descriptions
    """
    pool = await get_pool()

    rows = await pool.fetch("""
        SELECT
            t.table_name,
            COALESCE(obj_description((t.table_schema || '.' || t.table_name)::regclass), '') as description
        FROM information_schema.tables t
        WHERE t.table_schema = 'ats'
        AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name
    """)

    tables = {}
    for row in rows:
        tables[row["table_name"]] = row["description"] or "No description"

    return {
        "schema": "ats",
        "tables": tables,
        "hint": "Use discover_columns(table_name) to see columns for a specific table"
    }


async def discover_columns(tool_context: ToolContext, table_name: str) -> dict:
    """
    Discover columns for a specific table.

    Call this to understand the structure of a table before querying it.

    Args:
        table_name: Name of the table (e.g., 'vacancies', 'applications', 'agent_activities')

    Returns:
        Dictionary with column details including name, type, and if nullable
    """
    pool = await get_pool()

    rows = await pool.fetch("""
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default,
            COALESCE(col_description((table_schema || '.' || table_name)::regclass, ordinal_position), '') as description
        FROM information_schema.columns
        WHERE table_schema = 'ats' AND table_name = $1
        ORDER BY ordinal_position
    """, table_name)

    if not rows:
        return {"error": f"Table '{table_name}' not found in ats schema"}

    columns = []
    for row in rows:
        columns.append({
            "name": row["column_name"],
            "type": row["data_type"],
            "nullable": row["is_nullable"] == "YES",
            "description": row["description"] or None
        })

    return {
        "table": table_name,
        "columns": columns
    }


async def discover_relationships(tool_context: ToolContext) -> dict:
    """
    Discover foreign key relationships between tables.

    Call this to understand how tables are connected (for JOINs).

    Returns:
        List of foreign key relationships showing how tables connect
    """
    pool = await get_pool()

    rows = await pool.fetch("""
        SELECT
            tc.table_name as from_table,
            kcu.column_name as from_column,
            ccu.table_name as to_table,
            ccu.column_name as to_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = 'ats'
        ORDER BY tc.table_name
    """)

    relationships = []
    for row in rows:
        relationships.append({
            "from": f"{row['from_table']}.{row['from_column']}",
            "to": f"{row['to_table']}.{row['to_column']}",
            "join_hint": f"JOIN {row['to_table']} ON {row['from_table']}.{row['from_column']} = {row['to_table']}.{row['to_column']}"
        })

    return {
        "relationships": relationships,
        "hint": "Use these to write JOIN queries between related tables"
    }


# ============================================================================
# SQL Execution Tool
# ============================================================================

async def execute_sql(tool_context: ToolContext, query: str) -> dict:
    """
    Execute a read-only SQL query against the database.

    IMPORTANT:
    - Use 'ats.' prefix for all tables (e.g., ats.vacancies, ats.applications)
    - Only SELECT queries are allowed
    - Results limited to 100 rows
    - Timeout after 10 seconds

    Args:
        query: A SELECT SQL query. Must start with SELECT or WITH.

    Returns:
        Dictionary with rows, columns, and row count
    """
    pool = await get_pool()

    # Normalize and validate
    normalized = " ".join(query.split()).strip()
    query_lower = normalized.lower()

    # Security: Must be SELECT
    if not (query_lower.startswith("select") or query_lower.startswith("with")):
        return {
            "error": "Only SELECT queries allowed",
            "hint": "Start your query with SELECT or WITH"
        }

    # Security: Block dangerous keywords
    blocked = ["insert", "update", "delete", "drop", "truncate", "alter", "create",
               "grant", "revoke", "--", "/*", "*/"]
    for word in blocked:
        if word in query_lower:
            return {"error": f"Forbidden keyword: {word}"}

    # Security: No multiple statements
    query_no_strings = re.sub(r"'[^']*'", "", query)
    if ";" in query_no_strings.strip().rstrip(";"):
        return {"error": "Multiple statements not allowed"}

    # Add LIMIT if missing
    if "limit" not in query_lower:
        query = query.rstrip().rstrip(";") + f" LIMIT {SQL_MAX_ROWS}"

    try:
        async with asyncio.timeout(SQL_QUERY_TIMEOUT):
            rows = await pool.fetch(query)

        if not rows:
            return {"rows": [], "row_count": 0, "columns": [], "message": "No results"}

        columns = list(rows[0].keys())
        result_rows = []

        for row in rows[:SQL_MAX_ROWS]:
            row_dict = {}
            for key, value in row.items():
                if hasattr(value, "isoformat"):
                    row_dict[key] = value.isoformat()
                elif isinstance(value, (dict, list)):
                    row_dict[key] = value
                elif value is not None:
                    row_dict[key] = str(value) if not isinstance(value, (int, float, bool)) else value
                else:
                    row_dict[key] = None
            result_rows.append(row_dict)

        return {
            "rows": result_rows,
            "row_count": len(result_rows),
            "columns": columns,
            "truncated": len(rows) >= SQL_MAX_ROWS
        }

    except asyncio.TimeoutError:
        return {"error": "Query timed out (10s limit)", "hint": "Simplify query or add WHERE filters"}
    except asyncpg.PostgresError as e:
        return {"error": f"SQL error: {str(e)}", "hint": "Check table/column names with discover_columns"}
    except Exception as e:
        return {"error": f"Error: {str(e)}"}


async def sample_data(tool_context: ToolContext, table_name: str, limit: int = 5) -> dict:
    """
    Get sample rows from a table to understand the data.

    Useful to see actual values before writing complex queries.

    Args:
        table_name: Name of the table (e.g., 'vacancies', 'agent_activities')
        limit: Number of sample rows (default 5, max 20)

    Returns:
        Sample rows from the table
    """
    pool = await get_pool()
    limit = min(limit, 20)

    try:
        rows = await pool.fetch(f"SELECT * FROM ats.{table_name} ORDER BY created_at DESC LIMIT $1", limit)

        if not rows:
            return {"table": table_name, "rows": [], "message": "Table is empty"}

        columns = list(rows[0].keys())
        result_rows = []

        for row in rows:
            row_dict = {}
            for key, value in row.items():
                if hasattr(value, "isoformat"):
                    row_dict[key] = value.isoformat()
                elif isinstance(value, (dict, list)):
                    row_dict[key] = value
                elif value is not None:
                    row_dict[key] = str(value) if not isinstance(value, (int, float, bool)) else value
                else:
                    row_dict[key] = None
            result_rows.append(row_dict)

        return {
            "table": table_name,
            "columns": columns,
            "rows": result_rows,
            "row_count": len(result_rows)
        }
    except asyncpg.PostgresError as e:
        return {"error": f"Table error: {str(e)}", "hint": "Use discover_tables() to see available tables"}


# ============================================================================
# Agent Definition
# ============================================================================

instruction = """Je bent een data-analist voor Taloo met VOLLEDIGE TOEGANG tot de recruitment database.

## KRITIEKE REGEL
Je MOET ALTIJD je database tools gebruiken om vragen te beantwoorden.
Zeg NOOIT "ik heb geen toegang" of "ik kan dat niet zien" - je HEBT toegang via je tools!

## TAAL
Antwoord in het Nederlands (Vlaams nl-BE).

## JE TOOLS

Je hebt 5 tools om de database te bevragen:

1. `discover_tables()` - Toon alle beschikbare tabellen
2. `discover_columns(table_name)` - Toon kolommen van een tabel
3. `discover_relationships()` - Toon hoe tabellen verbonden zijn
4. `sample_data(table_name)` - Bekijk voorbeelddata
5. `execute_sql(query)` - Voer een SQL query uit

## WERKWIJZE

Bij ELKE vraag over data:
1. EERST: Gebruik discover_tables() of discover_columns() om te begrijpen wat er is
2. DAN: Schrijf een SQL query met execute_sql()
3. TENSLOTTE: Geef een duidelijk antwoord met de resultaten

## SQL REGELS

- Gebruik ALTIJD 'ats.' prefix: `SELECT * FROM ats.vacancies`
- Alleen SELECT queries (read-only)
- Max 100 rijen resultaat

## VOORBEELDEN

**Vraag: "Analyseer de pre-screening vragen"**
→ discover_columns("pre_screenings") om structuur te zien
→ discover_columns("pre_screening_questions") voor de vragen
→ execute_sql("SELECT * FROM ats.pre_screening_questions LIMIT 20")
→ Analyseer en geef feedback

**Vraag: "Hoeveel activiteiten zijn er?"**
→ execute_sql("SELECT COUNT(*) FROM ats.agent_activities")
→ Geef het aantal

**Vraag: "Welke vacatures hebben we?"**
→ execute_sql("SELECT title, company, status FROM ats.vacancies")
→ Toon overzicht

## RESPONSE STIJL

- Direct en beknopt
- Concrete cijfers en data
- Duidelijke samenvattingen
"""

root_agent = Agent(
    name="data_analist",
    model="gemini-3-pro-preview",
    instruction=instruction,
    description="Intelligente data analist die SQL queries schrijft om recruitment vragen te beantwoorden",
    tools=[
        discover_tables,
        discover_columns,
        discover_relationships,
        sample_data,
        execute_sql,
    ],
)
  