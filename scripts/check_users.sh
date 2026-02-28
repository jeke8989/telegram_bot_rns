#!/bin/bash
# Script to check users statistics in the database

echo "=== 📊 Статистика пользователей бота ==="
echo ""

# Total users
echo "📈 Общее количество пользователей:"
docker exec neuro-connector-db psql -U neuro_user -d neuro_connector -t -c "SELECT COUNT(DISTINCT telegram_id) FROM users;"
echo ""

# Users by date
echo "📅 Новые пользователи за последние 24 часа:"
docker exec neuro-connector-db psql -U neuro_user -d neuro_connector -t -c "SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '24 hours';"
echo ""

# Recent users
echo "👥 Последние 10 пользователей:"
docker exec neuro-connector-db psql -U neuro_user -d neuro_connector -c "
SELECT 
    telegram_id, 
    first_name, 
    username, 
    TO_CHAR(last_interaction, 'DD.MM.YYYY HH24:MI') as last_active
FROM users 
ORDER BY last_interaction DESC 
LIMIT 10;
"
echo ""

# Active users
echo "🟢 Активные пользователи (за последние 7 дней):"
docker exec neuro-connector-db psql -U neuro_user -d neuro_connector -t -c "SELECT COUNT(*) FROM users WHERE last_interaction > NOW() - INTERVAL '7 days';"
echo ""

# Blocked users
echo "🚫 Заблокированных пользователей:"
docker exec neuro-connector-db psql -U neuro_user -d neuro_connector -t -c "SELECT COUNT(*) FROM users WHERE is_blocked = true;"
echo ""

echo "=== ✅ Статистика обновлена ==="
