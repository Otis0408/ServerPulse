#!/bin/bash
# ServerPulse Agent - One-liner installer for Linux servers
# Usage: curl -sSL <url>/install.sh | bash
set -e

INSTALL_DIR="$HOME/.serverpulse"
SERVICE_NAME="serverpulse"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║   ServerPulse Agent - Installer      ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Create install dir
mkdir -p "$INSTALL_DIR"

# Download or copy agent script
if [ -f "$(dirname "$0")/monitor_agent.py" ]; then
    cp "$(dirname "$0")/monitor_agent.py" "$INSTALL_DIR/monitor_agent.py"
    echo "  ✓ Agent script installed"
else
    echo "  ✗ monitor_agent.py not found"
    exit 1
fi

chmod +x "$INSTALL_DIR/monitor_agent.py"

# Check Python3
if ! command -v python3 &>/dev/null; then
    echo "  ✗ Python3 not found. Installing..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq python3 >/dev/null
    elif command -v yum &>/dev/null; then
        sudo yum install -y python3 >/dev/null
    fi
fi
echo "  ✓ Python3: $(python3 --version)"

# Open firewall port
PORT=9730
if command -v ufw &>/dev/null; then
    sudo ufw allow $PORT/tcp 2>/dev/null && echo "  ✓ Firewall: port $PORT opened (ufw)" || true
elif command -v firewall-cmd &>/dev/null; then
    sudo firewall-cmd --permanent --add-port=$PORT/tcp 2>/dev/null && \
    sudo firewall-cmd --reload 2>/dev/null && \
    echo "  ✓ Firewall: port $PORT opened (firewalld)" || true
fi

# Create systemd service
if command -v systemctl &>/dev/null; then
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    sudo tee "$SERVICE_FILE" >/dev/null <<SVCEOF
[Unit]
Description=ServerPulse Monitoring Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
ExecStart=$(command -v python3) $INSTALL_DIR/monitor_agent.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
    sudo systemctl restart "$SERVICE_NAME"
    echo "  ✓ Systemd service created and started"

    # Wait for agent to print connection code
    sleep 2
    echo ""
    echo "  ┌──────────────────────────────────────────┐"
    echo "  │  Connection code:                        │"
    echo "  └──────────────────────────────────────────┘"
    echo ""
    # Run agent briefly to get the code
    python3 "$INSTALL_DIR/monitor_agent.py" --print-code 2>/dev/null || \
    journalctl -u "$SERVICE_NAME" --no-pager -n 20 2>/dev/null | grep -A1 "Connection Code" || \
    echo "  Run: journalctl -u serverpulse -n 20  to see the code"
else
    echo "  ⚠ No systemd found. Run manually:"
    echo "    python3 $INSTALL_DIR/monitor_agent.py"
fi

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  ✓ Installation Complete!            ║"
echo "  ╠══════════════════════════════════════╣"
echo "  ║  Manage:                             ║"
echo "  ║  • Status:  systemctl status $SERVICE_NAME ║"
echo "  ║  • Logs:    journalctl -u $SERVICE_NAME -f ║"
echo "  ║  • Stop:    systemctl stop $SERVICE_NAME   ║"
echo "  ║  • Restart: systemctl restart $SERVICE_NAME║"
echo "  ╚══════════════════════════════════════╝"
echo ""
