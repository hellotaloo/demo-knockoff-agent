#!/bin/bash
# Deploy to Cloud Run staging environment

echo "🚀 Deploying to Cloud Run staging..."

gcloud run deploy taloo-agent \
    --source . \
    --region europe-west1 \
    --project knockoff-bot-demo

echo "✅ Deployment complete!"


# gcloud run deploy taloo-agent --source . --region europe-west1 --project knockoff-bot-demo
