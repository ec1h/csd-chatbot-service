#!/bin/bash
# Start CSD Chatbot with Optimized Pipeline (10x Faster!)

cd "$(dirname "$0")"

echo "🚀 Starting CSD Chatbot (Optimized Pipeline)..."
echo ""

# Activate virtual environment
source venv/bin/activate

# Enable optimized pipeline
export USE_OPTIMIZED_PIPELINE=true

# Set database connection
export POSTGRES_URI="postgresql://postgres:YourSecurePassword123@localhost:5434/ec1"

# Start the app
echo "✓ Virtual environment activated"
echo "✓ Using OPTIMIZED classification pipeline"
echo "✓ Features: Network classifier, caching, hot-reload, monitoring"
echo "✓ Database: localhost:5434"
echo ""
echo "⚠️  First run: Downloads embedding model (~500MB, takes 10-15 min)"
echo "⚠️  Subsequent runs: Instant startup (uses cached data)"
echo ""
echo "Starting application..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 app.py
