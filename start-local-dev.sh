#!/bin/bash
# Start local development with ngrok tunnel

echo "🚀 Starting local development environment..."

# Start ngrok in the background
echo "📡 Starting ngrok tunnel..."
ngrok http 8080 > /dev/null &
NGROK_PID=$!

# Wait for ngrok to start
sleep 2

# Get the public URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | grep -o '"public_url":"https://[^"]*' | grep -o 'https://[^"]*' | head -1)

if [ -z "$NGROK_URL" ]; then
    echo "❌ Failed to get ngrok URL"
    kill $NGROK_PID 2>/dev/null
    exit 1
fi

echo "✅ Ngrok tunnel active: $NGROK_URL"
echo ""
echo "📋 Update these webhook URLs:"
echo "   Twilio WhatsApp: $NGROK_URL/webhook"
echo "   ElevenLabs Voice: $NGROK_URL/webhook/elevenlabs"
echo ""
echo "Press Ctrl+C to stop..."

# Start the backend
python -m uvicorn app:app --reload --port 8080

# Cleanup on exit
trap "kill $NGROK_PID 2>/dev/null" EXIT
