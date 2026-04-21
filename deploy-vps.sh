#!/bin/bash
# Federation Game - VPS Deployment Script
# Run this on srv1345984.hstgr.cloud

set -e

echo "🚀 Deploying Federation Game..."

# 1. Install Docker if needed
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
fi

# 2. Install docker-compose
if ! command -v docker-compose &> /dev/null; then
    echo "Installing docker-compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
fi

# 3. Create project directory
mkdir -p ~/federation-game
cd ~/federation-game

# 4. Clone or upload files (replace with your actual method)
# Option A: Git clone
# git clone https://github.com/yourusername/federation.git .

# Option B: SCP upload (run from local machine)
# scp -r S:\federation\public_html user@srv1345984.hstgr.cloud:~/federation-game/

# 5. Create nginx config
cat > nginx.conf << 'EOF'
server {
    listen 80;
    server_name _;
    
    root /usr/share/nginx/html;
    index index.html;
    
    gzip on;
    gzip_types text/html text/css application/javascript application/json;
    
    location / {
        try_files $uri $uri/ =404;
    }
    
    location /game/assets/ {
        expires 1d;
        add_header Cache-Control "public, immutable";
    }
    
    location ~ \.js$ {
        add_header Content-Type application/javascript;
    }
}
EOF

# 6. Create docker-compose
cat > docker-compose.yml << 'EOF'
version: '3.8'
services:
  game:
    image: nginx:alpine
    container_name: federation-game
    ports:
      - "80:80"
    volumes:
      - ./public_html:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    restart: unless-stopped
EOF

# 7. Start the game
docker-compose up -d

echo "✅ Federation Game deployed!"
echo "🌐 Visit: http://srv1345984.hstgr.cloud"
