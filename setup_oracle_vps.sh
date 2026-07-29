#!/bin/bash
# ============================================================
# setup_oracle_vps.sh
# One-shot script to bootstrap AstraQuote Lead Engine on a
# fresh Oracle Cloud Always Free ARM Ubuntu 22.04 VM.
# Run as: bash setup_oracle_vps.sh
# ============================================================
set -e

REPO_URL="https://github.com/akashjadon04/AstraQuoteLeadEngine.git"
APP_DIR="/opt/astraquote"
PORT=8800

echo "======================================"
echo " AstraQuote VPS Bootstrap"
echo "======================================"

# 1. System update
echo "[1/8] Updating system..."
sudo apt-get update -y && sudo apt-get upgrade -y

# 2. Install Docker
echo "[2/8] Installing Docker..."
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
sudo systemctl enable docker
sudo systemctl start docker

# 3. Install Docker Compose
echo "[3/8] Installing Docker Compose..."
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 4. Open firewall port
echo "[4/8] Opening firewall port $PORT..."
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport $PORT -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true
sudo ufw allow $PORT/tcp 2>/dev/null || true

# 5. Clone the repo
echo "[5/8] Cloning repository..."
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR
if [ -d "$APP_DIR/.git" ]; then
  cd $APP_DIR && git pull
else
  git clone $REPO_URL $APP_DIR
fi
cd $APP_DIR

# 6. Create persistent data directories
echo "[6/8] Setting up data directories..."
mkdir -p data exports logs

# 7. Build and run with Docker
echo "[7/8] Building Docker image (this takes 3-5 minutes first time)..."
sudo docker-compose down 2>/dev/null || true
sudo docker-compose up -d --build

# 8. Set up auto-restart on reboot
echo "[8/8] Enabling auto-start on reboot..."
sudo systemctl enable docker

# Done
PUBLIC_IP=$(curl -s ifconfig.me)
echo ""
echo "======================================"
echo " DONE! AstraQuote is LIVE 24/7"
echo "======================================"
echo ""
echo " Dashboard URL: http://$PUBLIC_IP:$PORT"
echo " Leads API:     http://$PUBLIC_IP:$PORT/api/leads"
echo " Export CSV:    http://$PUBLIC_IP:$PORT/api/export/csv"
echo ""
echo " App auto-restarts on reboot."
echo " To view logs: sudo docker-compose logs -f"
echo ""
