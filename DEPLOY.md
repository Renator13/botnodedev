# Deployment Protocol: BotNode.io

## Problem
- Homepage stuck on old version.
- `curl` returns `HTTP 405`.
- Docker and Python environments are broken.

## Solution: Hard Reboot & Rebuild

### Step 1: Reboot (Fix Docker Daemon)
```bash
sudo reboot
```

### Step 2: Install Docker (After Reboot)
```bash
sudo apt update && sudo apt install -y docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker
```

### Step 3: Deploy
```bash
cd /home/ubuntu/clawd/botnode_mvp
sudo docker-compose down
sudo docker-compose build --no-cache api
sudo docker-compose up -d
```

## Verification
```bash
curl -I https://botnode.io/
```
**Expected:** `HTTP 200` and `text/html`.
