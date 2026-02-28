#!/bin/bash

# Upload script - run this to upload files to server
# Password: aHVexY2#Da2?Rt

set -e

SERVER="root@217.198.13.11"
PROJECT_DIR="/Users/evgenijkukuskin/Documents/Проекты/cursor/NC_bot"

echo "🚀 Uploading files to server..."
echo "Password: aHVexY2#Da2?Rt"
echo ""

cd "$PROJECT_DIR"

echo "📁 Uploading mini_app..."
scp -r mini_app $SERVER:/tmp/nc-miniapp-upload/

echo "📁 Uploading app..."
scp -r app $SERVER:/tmp/nc-miniapp-upload/

echo "📁 Uploading Docker files..."
scp Dockerfile.webapp $SERVER:/tmp/nc-miniapp-upload/
scp requirements.txt $SERVER:/tmp/nc-miniapp-upload/
scp .env $SERVER:/tmp/nc-miniapp-upload/

echo "📁 Uploading configs..."
scp deploy/docker-compose.miniapp.yml $SERVER:/tmp/nc-miniapp-upload/docker-compose.yml
scp deploy/nginx-miniapp.conf $SERVER:/tmp/nc-miniapp-upload/miniapp.conf

echo ""
echo "✅ Files uploaded!"
echo ""
echo "Now run: ./setup-server.sh"
