#!/bin/bash

# Deployment script for Mini App
# Usage: ./deploy.sh

set -e

# Configuration
SERVER_IP="217.198.13.11"
SERVER_USER="root"
DEPLOY_PATH="/var/www/nc-miniapp"
DOMAIN="miniapp.neurosoft.pro"

echo "🚀 Starting deployment to $SERVER_IP..."

# Create deployment directory on server
echo "📁 Creating deployment directory..."
ssh $SERVER_USER@$SERVER_IP "mkdir -p $DEPLOY_PATH"

# Copy necessary files
echo "📤 Uploading files..."
scp -r ../mini_app $SERVER_USER@$SERVER_IP:$DEPLOY_PATH/
scp -r ../app $SERVER_USER@$SERVER_IP:$DEPLOY_PATH/
scp ../Dockerfile.webapp $SERVER_USER@$SERVER_IP:$DEPLOY_PATH/
scp ../requirements.txt $SERVER_USER@$SERVER_IP:$DEPLOY_PATH/
scp docker-compose.miniapp.yml $SERVER_USER@$SERVER_IP:$DEPLOY_PATH/docker-compose.yml
scp ../.env $SERVER_USER@$SERVER_IP:$DEPLOY_PATH/.env

# Copy Nginx configuration
echo "🔧 Setting up Nginx..."
scp nginx-miniapp.conf $SERVER_USER@$SERVER_IP:/tmp/miniapp.conf
ssh $SERVER_USER@$SERVER_IP "sudo mv /tmp/miniapp.conf /etc/nginx/sites-available/miniapp.neurosoft.pro"
ssh $SERVER_USER@$SERVER_IP "sudo ln -sf /etc/nginx/sites-available/miniapp.neurosoft.pro /etc/nginx/sites-enabled/"
ssh $SERVER_USER@$SERVER_IP "sudo nginx -t && sudo systemctl reload nginx"

# Build and start Docker containers
echo "🐳 Building and starting Docker containers..."
ssh $SERVER_USER@$SERVER_IP "cd $DEPLOY_PATH && docker-compose down || true"
ssh $SERVER_USER@$SERVER_IP "cd $DEPLOY_PATH && docker-compose build"
ssh $SERVER_USER@$SERVER_IP "cd $DEPLOY_PATH && docker-compose up -d"

# Setup SSL certificate (optional)
echo "🔒 Setting up SSL certificate..."
ssh $SERVER_USER@$SERVER_IP "sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email info@neurosoft.pro || echo 'SSL setup skipped or failed'"

echo "✅ Deployment completed!"
echo ""
echo "📋 DNS Configuration:"
echo "Add the following DNS record:"
echo "Type: A"
echo "Name: miniapp"
echo "Value: $SERVER_IP"
echo "TTL: 3600"
echo ""
echo "🌐 Your mini app will be available at: https://$DOMAIN"
echo ""
echo "📊 To check status:"
echo "ssh $SERVER_USER@$SERVER_IP 'cd $DEPLOY_PATH && docker-compose ps'"
echo ""
echo "📝 To view logs:"
echo "ssh $SERVER_USER@$SERVER_IP 'cd $DEPLOY_PATH && docker-compose logs -f'"
