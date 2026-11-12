#!/usr/bin/env bash
# =============================================================================
# SentinelIQ — EC2 Bootstrap Script
# Run once on a fresh Ubuntu 22.04 LTS / 24.04 LTS EC2 instance.
# Installs: Python 3.11+, Node.js 20 LTS, Docker Engine, Docker Compose v2,
#           Git, curl, jq, uv (Python package manager)
# =============================================================================

set -euo pipefail

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${BLUE}[bootstrap]${NC} $1"; }
ok()   { echo -e "${GREEN}[ok]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; exit 1; }

log "SentinelIQ EC2 Bootstrap — $(date -u)"
log "Running as: $(whoami) on $(uname -n)"

# -----------------------------------------------------------------------------
# 1. System update
# -----------------------------------------------------------------------------
log "Updating system packages..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
sudo apt-get install -y -qq \
    curl wget gnupg lsb-release ca-certificates \
    software-properties-common apt-transport-https \
    git jq build-essential unzip
ok "System packages updated"

# -----------------------------------------------------------------------------
# 2. Python 3.11+
# -----------------------------------------------------------------------------
log "Installing Python 3.11..."
PYTHON_VERSION=$(python3 --version 2>/dev/null | awk '{print $2}' || echo "0.0")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 11 ]]; then
    sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3.11 python3.11-venv python3.11-dev python3-pip
    sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
    ok "Python 3.11 installed"
else
    ok "Python $PYTHON_VERSION already satisfies >=3.11"
fi

python3 --version

# pip
log "Upgrading pip..."
python3 -m pip install --upgrade pip --quiet
ok "pip upgraded"

# uv — fast Python package manager
log "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
uv --version
ok "uv installed"

# -----------------------------------------------------------------------------
# 3. Node.js 20 LTS
# -----------------------------------------------------------------------------
log "Installing Node.js 20 LTS..."
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - 2>/dev/null
    sudo apt-get install -y -qq nodejs
    ok "Node.js installed"
else
    NODE_VERSION=$(node --version)
    ok "Node.js $NODE_VERSION already installed"
fi
node --version
npm --version

# -----------------------------------------------------------------------------
# 4. Docker Engine + Docker Compose v2
# -----------------------------------------------------------------------------
log "Installing Docker Engine..."
if ! command -v docker &>/dev/null; then
    # Remove old versions
    sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

    # Add Docker official GPG key and repository
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ok "Docker Engine installed"
else
    ok "Docker already installed: $(docker --version)"
fi

# Add ubuntu user to docker group (avoids sudo for docker commands)
if ! groups ubuntu 2>/dev/null | grep -q docker; then
    sudo usermod -aG docker ubuntu 2>/dev/null || true
    warn "Added ubuntu to docker group — log out and back in (or run 'newgrp docker') for this to take effect"
fi

docker --version
docker compose version

# Start and enable Docker
sudo systemctl start docker 2>/dev/null || true
sudo systemctl enable docker 2>/dev/null || true
ok "Docker service started"

# -----------------------------------------------------------------------------
# 5. Verify all tools
# -----------------------------------------------------------------------------
log "Verifying installed runtimes..."
echo ""
echo "─────────────────────────────────────────"
echo "  Runtime              Version"
echo "─────────────────────────────────────────"
printf "  Python3              %s\n" "$(python3 --version 2>&1)"
printf "  pip                  %s\n" "$(python3 -m pip --version 2>&1 | awk '{print $2}')"
printf "  uv                   %s\n" "$(uv --version 2>&1 || echo 'not in PATH yet')"
printf "  Node.js              %s\n" "$(node --version 2>&1)"
printf "  npm                  %s\n" "$(npm --version 2>&1)"
printf "  Docker               %s\n" "$(docker --version 2>&1)"
printf "  Docker Compose       %s\n" "$(docker compose version 2>&1)"
printf "  Git                  %s\n" "$(git --version 2>&1)"
printf "  curl                 %s\n" "$(curl --version 2>&1 | head -1)"
printf "  jq                   %s\n" "$(jq --version 2>&1)"
echo "─────────────────────────────────────────"
echo ""

# -----------------------------------------------------------------------------
# 6. Configure git (if not already set)
# -----------------------------------------------------------------------------
if [[ -z "$(git config --global user.email 2>/dev/null)" ]]; then
    warn "Git user not configured. Set with:"
    warn "  git config --global user.email 'you@example.com'"
    warn "  git config --global user.name 'Your Name'"
fi

# -----------------------------------------------------------------------------
# 7. Create project directory
# -----------------------------------------------------------------------------
PROJECT_DIR="$HOME/sentineliq"
if [[ ! -d "$PROJECT_DIR" ]]; then
    mkdir -p "$PROJECT_DIR"
    ok "Created project directory: $PROJECT_DIR"
else
    ok "Project directory already exists: $PROJECT_DIR"
fi

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo ""
ok "Bootstrap complete!"
echo ""
echo "Next steps:"
echo "  1. Log out and back in (or run 'newgrp docker') to activate docker group"
echo "  2. Clone or push your repository to $PROJECT_DIR"
echo "  3. cd $PROJECT_DIR"
echo "  4. cp backend/.env.example backend/.env && edit backend/.env"
echo "  5. cp infra/docker/.env.example .env && set a unique POSTGRES_PASSWORD"
echo "  6. docker compose --env-file .env -f infra/docker/docker-compose.yml up -d"
echo "  7. curl http://localhost:8000/health"
echo ""
