#!/usr/bin/env python3
"""Quick script to check which database environment you're connected to."""
import os
from dotenv import load_dotenv

load_dotenv()

db_url = os.environ.get("DATABASE_URL", "NOT SET")
environment = os.environ.get("ENVIRONMENT", "NOT SET")

print(f"Environment: {environment}")
print(f"Database URL: {db_url[:80]}...")

if "szascstjqkmssauvfaaj" in db_url:
    print("⚠️  CONNECTED TO PRODUCTION")
elif "svebhvifkcxrsbpxjptr" in db_url:
    print("✅ CONNECTED TO STAGING")
else:
    print("❓ Unknown database")
