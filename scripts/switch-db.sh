#!/bin/bash
# Switch DATABASE_URL between environments
#
# Usage:
#   ./scripts/switch-db.sh dev        # Local development (default)
#   ./scripts/switch-db.sh staging    # Staging / Cloud Run
#   ./scripts/switch-db.sh prod       # Production (use with caution!)

ENV_FILE="/Users/lunar/Desktop/sites/taloo-workspace/taloo-backend/.env"

# Environment connection details
DEV_REF="ukednydcpvuiyajwxfei"
DEV_PASSWORD="4qyzD67Psk88DSxA"

STAGING_REF="hkgwmikqnairjddcrlqm"
STAGING_PASSWORD="8sOoOgX8Xjrv00nD"

PROD_REF="beniqwbanoqhxyrjwulg"
PROD_PASSWORD="siLl5KiCRP682HKF"

case "$1" in
    dev)
        NEW_URL="postgresql+asyncpg://postgres.${DEV_REF}:${DEV_PASSWORD}@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
        sed -i '' "s|^DATABASE_URL=.*|DATABASE_URL=${NEW_URL}|" "$ENV_FILE"
        echo "✓ Switched to DEV database (${DEV_REF})"
        ;;
    staging)
        NEW_URL="postgresql+asyncpg://postgres.${STAGING_REF}:${STAGING_PASSWORD}@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
        sed -i '' "s|^DATABASE_URL=.*|DATABASE_URL=${NEW_URL}|" "$ENV_FILE"
        echo "✓ Switched to STAGING database (${STAGING_REF})"
        ;;
    prod)
        echo "⚠️  WARNING: You are switching to the PRODUCTION database!"
        echo "   This contains real client data. Are you sure? (y/N)"
        read -r CONFIRM
        if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
            echo "Cancelled."
            exit 0
        fi
        NEW_URL="postgresql+asyncpg://postgres.${PROD_REF}:${PROD_PASSWORD}@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
        sed -i '' "s|^DATABASE_URL=.*|DATABASE_URL=${NEW_URL}|" "$ENV_FILE"
        echo "✓ Switched to PRODUCTION database (${PROD_REF})"
        ;;
    *)
        echo "Usage: ./scripts/switch-db.sh [dev|staging|prod]"
        echo ""
        echo "  dev      Local development (safe to experiment)"
        echo "  staging  Staging environment (Cloud Run)"
        echo "  prod     Production (⚠️  real client data!)"
        ;;
esac
