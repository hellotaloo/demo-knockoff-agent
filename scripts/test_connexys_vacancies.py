"""
Test script: Fetch vacancies from Connexys/Salesforce.

Reads credentials from the integration_connections table,
authenticates via OAuth2 client_credentials, and runs a SOQL query
to fetch vacancies from cxsrec__cxsPosition__c.

Usage:
    python scripts/test_connexys_vacancies.py
"""
import asyncio
import json
import os
import sys

import httpx
import asyncpg
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
SF_API_VERSION = "v62.0"

VACANCY_SOQL = """
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
LIMIT 5
""".strip().replace("\n", " ")


async def get_connexys_credentials(pool: asyncpg.Pool) -> dict:
    """Fetch stored Connexys credentials from the database."""
    row = await pool.fetchrow("""
        SELECT ic.credentials
        FROM system.integration_connections ic
        JOIN system.integrations i ON i.id = ic.integration_id
        WHERE i.slug = 'connexys'
        LIMIT 1
    """)
    if not row:
        print("ERROR: No Connexys connection found in database.")
        print("Save credentials via PUT /integrations/connections/connexys first.")
        sys.exit(1)

    creds = row["credentials"]
    return json.loads(creds) if isinstance(creds, str) else creds


async def authenticate(client: httpx.AsyncClient, credentials: dict) -> tuple[str, str]:
    """Authenticate with Salesforce and return (access_token, instance_url)."""
    instance_url = credentials["instance_url"].rstrip("/")
    instance_url = instance_url.replace(".lightning.force.com", ".my.salesforce.com")
    token_url = f"{instance_url}/services/oauth2/token"

    print(f"Authenticating with {instance_url} ...")
    resp = await client.post(token_url, data={
        "grant_type": "client_credentials",
        "client_id": credentials["consumer_key"],
        "client_secret": credentials["consumer_secret"],
    })

    if resp.status_code != 200:
        error = resp.json().get("error_description", resp.text)
        print(f"ERROR: Authentication failed: {error}")
        sys.exit(1)

    data = resp.json()
    access_token = data["access_token"]
    sf_instance = data.get("instance_url", instance_url)
    print(f"Authenticated. Instance: {sf_instance}")
    return access_token, sf_instance


async def query_soql(client: httpx.AsyncClient, instance_url: str, token: str, soql: str) -> dict:
    """Execute a SOQL query and return the response."""
    url = f"{instance_url}/services/data/{SF_API_VERSION}/query"
    resp = await client.get(url, params={"q": soql}, headers={
        "Authorization": f"Bearer {token}",
    })

    if resp.status_code != 200:
        print(f"ERROR: SOQL query failed ({resp.status_code})")
        print(resp.text[:1000])
        sys.exit(1)

    return resp.json()


def print_vacancy(record: dict, index: int):
    """Pretty-print a single vacancy record."""
    print(f"\n{'='*60}")
    print(f"  #{index + 1}: {record.get('Name', '(no name)')}")
    print(f"{'='*60}")
    print(f"  ID:             {record['Id']}")
    print(f"  Status:         {record.get('cxsrec__Status__c', '?')}")
    print(f"  Client:         {record.get('cxsrec__Account_name__c', '?')}")
    print(f"  Location:       {record.get('job_vdab_worklocation__c', '?')}")
    print(f"  Country:        {record.get('cxsrec__Country__c', '?')}")
    print(f"  Contract:       {record.get('cxsrec__Contract_type__c', '?')}")
    print(f"  Sector:         {record.get('job_sector__c', '?')}")
    print(f"  Section:        {record.get('job_section__c', '?')}")
    print(f"  Language:       {record.get('job_language__c', '?')}")
    print(f"  Work regime:    {record.get('job_work_regime__c', '?')}")
    print(f"  Brand:          {record.get('job_brand__c', '?')}")
    print(f"  Start date:     {record.get('cxsrec__Job_start_date__c', '?')}")
    print(f"  Headcount:      {record.get('cxsrec__Number_of_employees_to_be_hired__c', '?')}")

    owner = record.get("Owner") or {}
    print(f"  Owner:          {owner.get('Name', '?')} ({owner.get('Email', '?')})")

    office = record.get("job_office__r") or {}
    print(f"  Office:         {office.get('Name', '?')} ({office.get('office_email__c', '?')})")

    print(f"  Created:        {record.get('CreatedDate', '?')}")
    print(f"  Last modified:  {record.get('LastModifiedDate', '?')}")

    desc = record.get("cxsrec__Job_description__c")
    if desc:
        # Show first 200 chars of HTML to confirm it's coming through
        print(f"  Description:    {desc[:200]}...")


async def main():
    print("Connexys Vacancy Fetch Test")
    print("-" * 40)

    pool = await asyncpg.create_pool(DATABASE_URL)

    try:
        credentials = await get_connexys_credentials(pool)
        print(f"Credentials loaded (instance: {credentials.get('instance_url', '?')})")

        async with httpx.AsyncClient(timeout=30.0) as client:
            token, instance_url = await authenticate(client, credentials)

            print(f"\nRunning SOQL query (LIMIT 5)...")
            result = await query_soql(client, instance_url, token, VACANCY_SOQL)

            total = result.get("totalSize", 0)
            records = result.get("records", [])
            done = result.get("done", True)

            print(f"\nTotal matching records: {total}")
            print(f"Records returned: {len(records)}")
            print(f"All fetched: {done}")

            for i, record in enumerate(records):
                print_vacancy(record, i)

            # Also print status distribution
            print(f"\n{'='*60}")
            print("Status values in this batch:")
            statuses = {}
            for r in records:
                s = r.get("cxsrec__Status__c", "?")
                statuses[s] = statuses.get(s, 0) + 1
            for s, count in sorted(statuses.items()):
                print(f"  {s}: {count}")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
