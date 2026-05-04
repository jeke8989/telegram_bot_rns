#!/bin/bash

# Setup server script
# Password: aHVexY2#Da2?Rt

SERVER="root@217.198.13.11"

echo "🔧 Setting up server..."
echo "Password: aHVexY2#Da2?Rt"
echo ""

ssh $SERVER << 'ENDSSH'
set -e

echo "📁 Creating deployment directory..."
mkdir -p /var/www/nc-miniapp
cp -r /tmp/nc-miniapp-upload/* /var/www/nc-miniapp/

echo "🔧 Setting up Nginx..."
mv /var/www/nc-miniapp/miniapp.conf /etc/nginx/sites-available/miniapp.neurosoft.pro
ln -sf /etc/nginx/sites-available/miniapp.neurosoft.pro /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx

echo "🐳 Starting Docker containers..."
cd /var/www/nc-miniapp
docker-compose down || true
docker-compose build
docker-compose up -d

echo ""
echo "✅ Setup completed!"
echo ""
echo "📊 Container status:"
docker-compose ps

echo ""
echo "📝 To view logs:"
echo "docker-compose logs -f"
ENDSSH

echo ""
echo "✅ Server setup completed!"
echo ""
echo "🌐 Your mini app will be available at: https://miniapp.neurosoft.pro"
echo "⏳ Wait 10-15 minutes for DNS to propagate"
