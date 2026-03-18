#!/bin/bash
# Switch DATABASE_URL between main and a preview branch
#
# Usage:
#   ./scripts/switch-db.sh main              # Switch to main DB
#   ./scripts/switch-db.sh preview <ref> <password>  # Switch to preview branch
#
# The preview ref and password are shown in Supabase dashboard → Branches → click branch → Connect

ENV_FILE="/Users/lunar/Desktop/sites/taloo-workspace/taloo-backend/.env"
MAIN_REF="beniqwbanoqhxyrjwulg"
MAIN_PASSWORD="siLl5KiCRP682HKF"

if [ "$1" = "main" ]; then
    NEW_URL="postgresql+asyncpg://postgres.${MAIN_REF}:${MAIN_PASSWORD}@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
    sed -i '' "s|^DATABASE_URL=.*|DATABASE_URL=${NEW_URL}|" "$ENV_FILE"
    echo "Switched to MAIN DB (${MAIN_REF})"

elif [ "$1" = "preview" ]; then
    REF="$2"
    PASSWORD="$3"

    if [ -z "$REF" ] || [ -z "$PASSWORD" ]; then
        echo "Usage: ./scripts/switch-db.sh preview <project-ref> <password>"
        echo ""
        echo "Find these in Supabase → Branches → click your preview branch → Connect"
        exit 1
    fi

    NEW_URL="postgresql+asyncpg://postgres.${REF}:${PASSWORD}@aws-1-eu-west-1.pooler.supabase.com:5432/postgres"
    sed -i '' "s|^DATABASE_URL=.*|DATABASE_URL=${NEW_URL}|" "$ENV_FILE"
    echo "Switched to PREVIEW branch (${REF})"

else
    echo "Usage:"
    echo "  ./scripts/switch-db.sh main                        # Switch to main DB"
    echo "  ./scripts/switch-db.sh preview <ref> <password>    # Switch to preview branch"
fi
