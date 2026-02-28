#!/bin/bash

# Deploy script for NC_bot
# Credentials are loaded from .env (only SERVER_* lines to avoid syntax issues)
SERVER_HOST=$(grep '^SERVER_HOST=' .env | cut -d'=' -f2)
SERVER_USER=$(grep '^SERVER_USER=' .env | cut -d'=' -f2)
SERVER_PASSWORD=$(grep '^SERVER_PASSWORD=' .env | cut -d'=' -f2-)

SERVER="${SERVER_USER:-root}@${SERVER_HOST:-217.198.13.11}"
PASSWORD="${SERVER_PASSWORD}"
REMOTE_DIR="/var/www/nc-miniapp"

echo "Deploying files to server..."

# Deploy app files
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no \
    app/bot.py \
    app/lark_client.py \
    app/zoom_client.py \
    app/zoom_ws_listener.py \
    app/database.py \
    app/kimai_client.py \
    app/config.py \
    "$SERVER:$REMOTE_DIR/app/"

# Deploy app/assets (client banners etc.)
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$SERVER" "mkdir -p $REMOTE_DIR/app/assets"
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no \
    app/assets/welcome_client_banner.png \
    "$SERVER:$REMOTE_DIR/app/assets/"

# Deploy root assets (welcome_banner, business_card etc.)
# These are mounted as ./assets:/app/assets in docker-compose for the bot container
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$SERVER" "mkdir -p $REMOTE_DIR/assets"
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no \
    assets/welcome_client_banner.png \
    assets/business_card_banner.png \
    assets/logo.jpg \
    "$SERVER:$REMOTE_DIR/assets/"

# Deploy docker-compose.yml (env vars for new features)
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no \
    docker-compose.yml \
    "$SERVER:$REMOTE_DIR/"

# Deploy mini_app files
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no \
    mini_app/server.py \
    "$SERVER:$REMOTE_DIR/mini_app/"

# Deploy app/middleware
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$SERVER" "mkdir -p $REMOTE_DIR/app/middleware"
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no \
    app/middleware/*.py \
    "$SERVER:$REMOTE_DIR/app/middleware/"

# Deploy app/routes
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$SERVER" "mkdir -p $REMOTE_DIR/app/routes"
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no \
    app/routes/*.py \
    "$SERVER:$REMOTE_DIR/app/routes/"

# Deploy static files (HTML, images, sidebar, roulette)
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no \
    mini_app/static/style.css \
    mini_app/static/script.js \
    mini_app/static/sidebar.js \
    mini_app/static/chat-widget.js \
    mini_app/static/index.html \
    mini_app/static/client-cabinet.html \
    mini_app/static/meeting.html \
    mini_app/static/login.html \
    mini_app/static/projects.html \
    mini_app/static/project.html \
    mini_app/static/proposal.html \
    mini_app/static/proposals.html \
    mini_app/static/proposal-edit.html \
    mini_app/static/clients.html \
    mini_app/static/client.html \
    mini_app/static/employees.html \
    mini_app/static/users.html \
    mini_app/static/seller.html \
    mini_app/static/og-meeting.png \
    mini_app/static/og-meeting.jpg \
    mini_app/static/og-proposal.png \
    "$SERVER:$REMOTE_DIR/mini_app/static/"

# Deploy refactored CSS (tokens, base, components, layouts)
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$SERVER" "mkdir -p $REMOTE_DIR/mini_app/static/css/components $REMOTE_DIR/mini_app/static/css/layouts"
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no \
    mini_app/static/css/tokens.css \
    mini_app/static/css/base.css \
    "$SERVER:$REMOTE_DIR/mini_app/static/css/"
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no mini_app/static/css/components/*.css "$SERVER:$REMOTE_DIR/mini_app/static/css/components/"
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no mini_app/static/css/layouts/*.css "$SERVER:$REMOTE_DIR/mini_app/static/css/layouts/"

# Deploy refactored JS (utils, components, pages)
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$SERVER" "mkdir -p $REMOTE_DIR/mini_app/static/js/utils $REMOTE_DIR/mini_app/static/js/components $REMOTE_DIR/mini_app/static/js/pages"
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no mini_app/static/js/utils/*.js "$SERVER:$REMOTE_DIR/mini_app/static/js/utils/"
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no mini_app/static/js/components/*.js "$SERVER:$REMOTE_DIR/mini_app/static/js/components/"
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no mini_app/static/js/pages/*.js "$SERVER:$REMOTE_DIR/mini_app/static/js/pages/"

echo "Restarting services..."

# Restart Docker containers (restart to pick up updated source files)
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no "$SERVER" << 'EOF'
cd /var/www/nc-miniapp
docker compose restart webapp bot
echo "Services restarted!"
docker ps
EOF

echo "Deployment complete!"
