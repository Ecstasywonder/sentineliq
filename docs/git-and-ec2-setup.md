# SentinelIQ — Git & EC2 Setup Guide

This document explains how to set up the Git repository and deploy to EC2.

---

## 1. Initialize the Git Repository (local machine)

In the `SentinelIQ Project` folder, open Git Bash (right-click → "Git Bash Here"):

```bash
git init
git add .
git commit -m "chore: Gate 0 — initial repository scaffold"
```

---

## 2. GitHub Authentication — SSH Keys (recommended)

GitHub no longer accepts passwords for Git operations. Use **SSH key authentication** — this works on both your local machine and EC2.

### Option A — SSH Key (recommended for both local and EC2)

**On your local machine (Git Bash):**

```bash
# Check if you already have an SSH key
ls ~/.ssh/id_ed25519.pub

# If not, generate one:
ssh-keygen -t ed25519 -C "your-email@example.com"
# Press Enter to accept defaults

# Copy the public key to clipboard:
cat ~/.ssh/id_ed25519.pub
```

1. Go to https://github.com/settings/keys
2. Click **New SSH key**
3. Paste your public key and save

Now configure Git to use SSH:

```bash
# Use SSH remote URL (not HTTPS)
git remote add origin git@github.com:YOUR_USERNAME/sentineliq.git
```

**On EC2 (same process):**

```bash
# On EC2 — generate a key for the server
ssh-keygen -t ed25519 -C "sentineliq-ec2"
cat ~/.ssh/id_ed25519.pub
# Add this key to GitHub → Settings → SSH keys (same as above)
```

### Option B — Personal Access Token (PAT) with HTTPS

If you prefer HTTPS over SSH:

1. Go to https://github.com/settings/tokens
2. Click **Generate new token (classic)**
3. Select scopes: `repo` (full control of private repositories)
4. Copy the token — **it is shown only once**

Use it as your password when Git prompts (or store it in Git credential manager):

```bash
git config --global credential.helper store
# On first push, enter: username = YOUR_USERNAME, password = YOUR_PAT_TOKEN
```

Or embed it in the remote URL (less secure — avoid on shared machines):

```bash
git remote add origin https://YOUR_USERNAME:YOUR_PAT@github.com/YOUR_USERNAME/sentineliq.git
```

### Option C — GitHub CLI (`gh`)

```bash
# Install GitHub CLI
winget install GitHub.cli        # Windows (local)
# or on EC2:
sudo apt install gh

# Authenticate
gh auth login
# Follow the prompts — no password needed

# Then clone/push as normal
```

---

## 3. Create a GitHub Repository

1. Go to https://github.com/new
2. Name it `sentineliq`
3. Set visibility (Private recommended)
4. Do NOT initialize with a README (we already have one)
5. Click "Create repository"

Then push (using SSH remote):

```bash
git remote add origin git@github.com:YOUR_USERNAME/sentineliq.git
git branch -M main
git push -u origin main
```

---

## 4. Bootstrap the EC2 Server

SSH into your EC2 instance:

```bash
ssh -i ~/.ssh/"test key.pem" ubuntu@98.81.243.2
```

Run the bootstrap script:

```bash
# Option A: Download directly from GitHub (after pushing)
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/sentineliq/main/infra/docker/bootstrap-ec2.sh | bash

# Option B: Copy the script via scp from your local machine
scp -i ~/.ssh/"test key.pem" "infra/docker/bootstrap-ec2.sh" ubuntu@98.81.243.2:~/
ssh -i ~/.ssh/"test key.pem" ubuntu@98.81.243.2
chmod +x ~/bootstrap-ec2.sh
./bootstrap-ec2.sh
```

---

## 5. Clone the Repository on EC2

After bootstrap completes, set up SSH auth on EC2 (Option A above), then:

```bash
# On EC2 — clone via SSH:
git clone git@github.com:YOUR_USERNAME/sentineliq.git ~/sentineliq
cd ~/sentineliq

# Or via HTTPS + PAT:
git clone https://YOUR_USERNAME:YOUR_PAT@github.com/YOUR_USERNAME/sentineliq.git ~/sentineliq
cd ~/sentineliq
```

---

## 5. Verify Environment on EC2

Run this and **paste the output back to IBM Bob**:

```bash
echo "=== Environment Verification ===" && \
python3 --version && \
node --version && \
npm --version && \
docker --version && \
docker compose version && \
git --version && \
uv --version 2>/dev/null || echo "uv: not in PATH (may need: source ~/.bashrc)" && \
echo "Disk:" && df -h / && \
echo "Memory:" && free -h && \
echo "=== Done ==="
```

---

## 6. Ongoing Development Workflow

### When IBM Bob makes changes (local machine):

```bash
# In Git Bash in the SentinelIQ Project folder:
git add .
git commit -m "gate-N: description of changes"
git push origin main
```

### On EC2 (pull and apply):

```bash
cd ~/sentineliq
git pull origin main
```

Then run whatever commands IBM Bob specifies for that gate.

---

## 7. .gitignore Note

The `.gitignore` file content is below. Create it manually in the project root:

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
dist/
*.egg-info/
.pytest_cache/
htmlcov/
.coverage
.coverage.*
.tox/
.nox/

# Virtual environments
.env
.venv
env/
venv/

# Environment files (NEVER commit secrets)
backend/.env
backend/.env.local
backend/.env.production
frontend/.env
frontend/.env.local
frontend/.env.production
.env.*
!.env.example
!backend/.env.example
!frontend/.env.example

# Node
node_modules/
frontend/dist/
frontend/dist-ssr/
frontend/.vite/
*.tsbuildinfo

# Testing
frontend/coverage/
backend/htmlcov/

# IDEs
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store
Thumbs.db

# Docker
infra/docker/.env

# Database
*.db
*.sqlite

# Logs
*.log
logs/

# Secrets / keys
*.pem
*.key
*.p12
*.pfx
*.crt
*.cer

# Evaluation reports (generated)
evaluations/reports/*.json
evaluations/reports/*.html

# Temporary
tmp/
temp/
.tmp/
```

**To create this file:**

In Git Bash:
```bash
# Copy the content above into a file named .gitignore in the project root
# You can use: notepad .gitignore  (in the project root)
# Or: cat > .gitignore   then paste content, then Ctrl+D
```
