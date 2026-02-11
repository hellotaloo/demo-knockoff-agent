#!/bin/bash
# Start local development with ngrok tunnel
# Optional: set NGROK_DOMAIN in .env to use a fixed reserved domain (paid account).

echo "🚀 Starting local development environment..."

# Load NGROK_DOMAIN from .env if not already set (e.g. your reserved domain: taloo-dev.ngrok.app)
if [ -z "${NGROK_DOMAIN:-}" ] && [ -f .env ]; then
    NGROK_DOMAIN=$(grep -E '^NGROK_DOMAIN=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
fi

# Kill any existing ngrok so we get a fresh tunnel and the correct URL from localhost:4040
if pgrep -f "ngrok http" > /dev/null; then
    echo "📡 Stopping existing ngrok tunnel..."
    pkill -f "ngrok http" 2>/dev/null || true
    sleep 2
fi

# Start ngrok in the background (with fixed domain if set)
if [ -n "${NGROK_DOMAIN:-}" ]; then
    echo "📡 Starting ngrok tunnel (fixed domain: $NGROK_DOMAIN)..."
    ngrok http --domain "$NGROK_DOMAIN" 8080 > /dev/null &
else
    echo "📡 Starting ngrok tunnel (random URL; set NGROK_DOMAIN in .env for a fixed domain)..."
    ngrok http 8080 > /dev/null &
fi
NGROK_PID=$!

# Wait for ngrok to start
sleep 2

# Get the public HTTPS URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for t in d.get('tunnels', []):
        u = t.get('public_url', '')
        if u.startswith('https://'):
            print(u)
            break
except Exception:
    pass
" 2>/dev/null)

if [ -z "$NGROK_URL" ]; then
    echo "❌ Failed to get ngrok URL (check ngrok is logged in and, if using NGROK_DOMAIN, that the domain is reserved in your ngrok dashboard)"
    kill $NGROK_PID 2>/dev/null
    exit 1
fi

echo "✅ Ngrok tunnel active: $NGROK_URL"
echo ""
echo "📋 Webhook URLs (set in Twilio / ElevenLabs):"
echo "   Twilio WhatsApp:  $NGROK_URL/webhook"
echo "   ElevenLabs Voice: $NGROK_URL/webhook/elevenlabs"
echo ""
[ -n "${NGROK_DOMAIN:-}" ] && echo "   (Fixed domain – URL stays the same across restarts.)"
echo "Press Ctrl+C to stop..."

# Start the backend
python -m uvicorn app:app --reload --port 8080

# Cleanup on exit
trap "kill $NGROK_PID 2>/dev/null" EXIT
