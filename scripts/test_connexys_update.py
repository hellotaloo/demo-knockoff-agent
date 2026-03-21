"""
Quick test: update a Taloo field on a Connexys job application record.
"""
import asyncio
import json
import httpx
import asyncpg


async def main():
    # 1. Get credentials from DB
    db_url = "postgresql://postgres.cruwmzrgbserobxdwcgj:F84DVuAzoZmw70dY@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
    conn = await asyncpg.connect(db_url)

    row = await conn.fetchrow("""
        SELECT ic.credentials, ic.settings, i.slug
        FROM system.integration_connections ic
        JOIN system.integrations i ON i.id = ic.integration_id
        WHERE i.slug = 'connexys' AND ic.is_active = true
        LIMIT 1
    """)
    await conn.close()

    if not row:
        print("No active Connexys connection found!")
        return

    credentials = json.loads(row["credentials"]) if isinstance(row["credentials"], str) else row["credentials"]
    print(f"Found credentials for instance: {credentials['instance_url']}")

    # 2. Authenticate to Salesforce
    instance_url = credentials["instance_url"].rstrip("/").replace(".lightning.force.com", ".my.salesforce.com")
    token_url = f"{instance_url}/services/oauth2/token"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(token_url, data={
            "grant_type": "client_credentials",
            "client_id": credentials["consumer_key"],
            "client_secret": credentials["consumer_secret"],
        })

        if resp.status_code != 200:
            print(f"Auth failed: {resp.status_code} {resp.text}")
            return

        token_data = resp.json()
        access_token = token_data["access_token"]
        sf_instance = token_data.get("instance_url", instance_url)
        print(f"Authenticated to: {sf_instance}")

        headers = {"Authorization": f"Bearer {access_token}"}
        sf_api = f"{sf_instance}/services/data/v62.0"

        # 3. Find the "Jan Van Damme" job application record
        soql = (
            "SELECT Id, Name FROM cxsrec__cxsJob_application__c "
            "WHERE Name LIKE '%Jan Van Damme%' LIMIT 5"
        )
        print(f"\nSearching: {soql}")

        resp = await client.get(f"{sf_api}/query", params={"q": soql}, headers=headers)
        if resp.status_code != 200:
            print(f"Query failed: {resp.status_code} {resp.text[:500]}")
            return

        records = resp.json().get("records", [])
        if not records:
            print("No records found! Trying broader search...")
            soql2 = "SELECT Id, Name FROM cxsrec__cxsJob_application__c ORDER BY LastModifiedDate DESC LIMIT 5"
            resp = await client.get(f"{sf_api}/query", params={"q": soql2}, headers=headers)
            records = resp.json().get("records", [])

        for r in records:
            print(f"  - {r['Id']}: {r['Name']}")

        if not records:
            print("No job application records found at all!")
            return

        # Pick the first match
        record_id = records[0]["Id"]
        record_name = records[0]["Name"]
        print(f"\nUsing record: {record_name} ({record_id})")

        # 4. Try updating a Taloo field
        update_payload = {
            "Taloo_gekwalificeerd__c": True,
        }
        print(f"\nUpdating with: {json.dumps(update_payload, indent=2)}")

        resp = await client.patch(
            f"{sf_api}/sobjects/cxsrec__cxsJob_application__c/{record_id}",
            json=update_payload,
            headers={**headers, "Content-Type": "application/json"},
        )

        if resp.status_code in (200, 204):
            print(f"SUCCESS! Updated {record_name}")
        else:
            print(f"FAILED ({resp.status_code}): {resp.text[:500]}")

        # 5. Verify by reading back
        verify_soql = (
            f"SELECT Id, Name, Taloo_gekwalificeerd__c, Taloo_samenvatting__c, "
            f"Taloo_kwalificatiescore__c, Taloo_interviewmoment__c, "
            f"Taloo_afgerond_op__c, Taloo_vragen_antwoorden__c "
            f"FROM cxsrec__cxsJob_application__c WHERE Id = '{record_id}'"
        )
        resp = await client.get(f"{sf_api}/query", params={"q": verify_soql}, headers=headers)
        if resp.status_code == 200:
            result = resp.json().get("records", [{}])[0]
            print(f"\nVerification read-back:")
            for key, val in result.items():
                if key != "attributes":
                    print(f"  {key}: {val}")
        else:
            print(f"Verify query failed: {resp.status_code} {resp.text[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
