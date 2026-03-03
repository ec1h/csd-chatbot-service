#!/bin/bash
# Start CSD Chatbot with Legacy Pipeline (Fast!)

cd "$(dirname "$0")"

echo "🚀 Starting CSD Chatbot (Legacy Pipeline)..."
echo ""

# Activate virtual environment
source venv/bin/activate

# Disable optimized pipeline for fast startup
export USE_OPTIMIZED_PIPELINE=false

# Set database connection
export POSTGRES_URI="postgresql://postgres:YourSecurePassword123@localhost:5434/ec1"

# Start the app
echo "✓ Virtual environment activated"
echo "✓ Using legacy classification pipeline (fast startup)"
echo "✓ Database: localhost:5434"
echo ""
echo "Starting application..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 app.py
