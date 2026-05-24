#!/usr/bin/env bash
# ── Fantasy Draft Dashboard — First-time setup ──────────────────────────────
set -e

echo "🏈 Setting up Fantasy Draft Dashboard..."

# Check Python version
python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
major=$(echo $python_version | cut -d. -f1)
minor=$(echo $python_version | cut -d. -f2)
if [ "$major" -lt 3 ] || ([ "$major" -eq 3 ] && [ "$minor" -lt 10 ]); then
    echo "❌ Python 3.10+ required (found $python_version)"
    exit 1
fi
echo "✅ Python $python_version found"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Create cache directory
mkdir -p data/cache

echo ""
echo "✅ Setup complete!"
echo ""
echo "👉  To start the dashboard:"
echo "    source .venv/bin/activate"
echo "    streamlit run app.py"
echo ""
echo "Then open http://localhost:8501 in your browser."
