#!/bin/bash
set -e

echo "=========================================="
echo "  IdeaForge Installation"
echo "=========================================="
echo ""

# Check Python version
echo "→ Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 not found. Please install Python 3.10 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo "✗ Python 3.10+ required. Found: $PYTHON_VERSION"
    exit 1
fi

echo "✓ Python $PYTHON_VERSION found"
echo ""

# Create virtual environment
echo "→ Creating virtual environment (.ideaforge)..."
if [ -d ".ideaforge" ]; then
    echo "  Virtual environment already exists, skipping..."
else
    python3 -m venv .ideaforge
    echo "✓ Virtual environment created"
fi
echo ""

# Activate and install dependencies
echo "→ Installing dependencies..."
source .ideaforge/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Verify critical imports
echo ""
echo "→ Verifying installation..."
python3 << 'EOF'
import sys
try:
    import dotenv
    import yt_dlp
    import feedparser
    print("✓ Core dependencies OK")
    try:
        import google.genai
        print("✓ Gemini backend available")
    except ImportError:
        print("⚠ Gemini backend not available (optional)")
    sys.exit(0)
except ImportError as e:
    print(f"✗ Dependency check failed: {e}")
    sys.exit(1)
EOF

if [ $? -ne 0 ]; then
    echo ""
    echo "✗ Installation failed. Please check errors above."
    exit 1
fi

echo ""

# Create .env template if not exists
if [ ! -f .env ]; then
    echo "→ Creating .env template..."
    cat > .env << 'EOF'
# IdeaForge Configuration
# Add your API keys below

# Required: At least one AI backend
GEMINI_API_KEY=your-gemini-key-here
# ANTHROPIC_API_KEY=your-anthropic-key-here

# Optional: Model selection
# MODEL=gemini-2.0-flash-exp
# MODEL=claude-sonnet-4-5
EOF
    chmod 600 .env
    echo "✓ Created .env template (chmod 600)"
else
    echo "→ .env already exists, skipping..."
fi

echo ""
echo "=========================================="
echo "  Installation Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Edit .env and add your API key:"
echo "     $ nano .env"
echo ""
echo "  2. Start IdeaForge:"
echo "     $ source .ideaforge/bin/activate"
echo "     $ ./ideaforge"
echo ""
echo "  3. Open in browser:"
echo "     http://localhost:7888"
echo ""
echo "Documentation: See README.md"
echo ""
