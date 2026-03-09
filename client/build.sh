#!/bin/bash
# Build ServerPulse.app for macOS
set -e

cd "$(dirname "$0")"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   ServerPulse - Build macOS App      ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Setup venv
if [ ! -d "venv" ]; then
    echo "  📦 Creating virtual environment..."
    python3 -m venv venv
fi

echo "  📦 Installing dependencies..."
venv/bin/pip install -q -r requirements.txt

# Generate icon
echo "  🎨 Generating app icon..."
venv/bin/python create_icon.py

# Clean previous builds
rm -rf build dist

# Build app
echo "  🔨 Building ServerPulse.app..."
venv/bin/python setup_app.py py2app 2>&1 | tail -3

if [ -d "dist/ServerPulse.app" ]; then
    echo ""
    echo "  ✅ Build successful!"
    echo ""

    # Copy to /Applications
    if [ -d "/Applications/ServerPulse.app" ]; then
        echo "  🗑  Removing old version..."
        rm -rf "/Applications/ServerPulse.app"
    fi
    cp -R dist/ServerPulse.app /Applications/
    echo "  📁 Installed to /Applications/ServerPulse.app"

    echo ""
    echo "  ╔══════════════════════════════════════╗"
    echo "  ║  ✓ Launch from Applications folder   ║"
    echo "  ║    or run: open /Applications/       ║"
    echo "  ║    ServerPulse.app                   ║"
    echo "  ╚══════════════════════════════════════╝"
    echo ""
else
    echo "  ❌ Build failed"
    exit 1
fi
