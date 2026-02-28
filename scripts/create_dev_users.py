#!/usr/bin/env python3
"""
Создание тестовых пользователей для dev-окружения
Запуск: python scripts/create_dev_users.py
"""

import asyncio
import asyncpg
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv('.env.dev')

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://neuro_user:neuro_password@localhost:5435/neuro_connector')

TEST_USERS = [
    {
        'telegram_id': 1000001,
        'first_name': 'Админ',
        'last_name': 'Тестовый',
        'username': 'admin_test',
        'role': 'admin',
    },
    {
        'telegram_id': 1000002,
        'first_name': 'Евгений',
        'last_name': 'Разработчик',
        'username': 'staff_dev',
        'role': 'staff',
        'staff_specialty': 'backend',
        'staff_grade': 'Senior',
        'staff_display_name': 'Евгений (Backend)',
    },
    {
        'telegram_id': 1000003,
        'first_name': 'Анастасия',
        'last_name': 'PM',
        'username': 'staff_pm',
        'role': 'staff',
        'staff_specialty': 'management',
        'staff_grade': 'Lead',
        'staff_display_name': 'Анастасия (PM)',
    },
    {
        'telegram_id': 1000004,
        'first_name': 'Сергей',
        'last_name': 'Продавец',
        'username': 'seller_test',
        'role': 'seller',
    },
    {
        'telegram_id': 1000005,
        'first_name': 'Клиент',
        'last_name': 'Тестовый',
        'username': 'user_test',
        'role': 'user',
        'company': 'ООО "Тестовая компания"',
        'email': 'client@test.ru',
        'phone': '+7 (999) 123-45-67',
        'position': 'CEO',
        'client_status': 'client',
        'cabinet_token': 'test_client_token_12345',
    },
    {
        'telegram_id': 1000006,
        'first_name': 'Лид',
        'last_name': 'Новый',
        'username': 'user_lead',
        'role': 'user',
        'company': 'ООО "Потенциальный клиент"',
        'email': 'lead@test.ru',
        'phone': '+7 (999) 999-99-99',
        'position': 'CTO',
        'client_status': 'lead',
        'cabinet_token': 'test_lead_token_67890',
    },
]


async def main():
    print("=== Создание тестовых пользователей для dev ===\n")
    
    # Парсим DATABASE_URL для подключения (заменяем имя контейнера на localhost)
    db_url = DATABASE_URL.replace('postgres-dev', 'localhost')
    
    try:
        conn = await asyncpg.connect(db_url)
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        print(f"   URL: {db_url}")
        print("\n💡 Убедитесь что dev-контейнер запущен:")
        print("   docker compose -f docker-compose.dev.yml --env-file .env.dev up -d")
        sys.exit(1)
    
    print(f"✅ Подключено к БД: {db_url}\n")
    
    # Проверка существования таблицы users
    table_exists = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users')"
    )
    
    if not table_exists:
        print("❌ Таблица 'users' не найдена. Запустите webapp-dev для инициализации БД.")
        await conn.close()
        sys.exit(1)
    
    created = 0
    updated = 0
    
    for user in TEST_USERS:
        telegram_id = user['telegram_id']
        first_name = user['first_name']
        last_name = user.get('last_name', '')
        username = user.get('username', '')
        role = user['role']
        
        existing = await conn.fetchval(
            "SELECT telegram_id FROM users WHERE telegram_id = $1",
            telegram_id,
        )
        
        if existing:
            # Обновляем роль и поля
            await conn.execute("""
                UPDATE users SET
                    first_name = $2,
                    last_name = $3,
                    username = $4,
                    role = $5,
                    company = $6,
                    email = $7,
                    phone = $8,
                    position = $9,
                    client_status = $10,
                    cabinet_token = $11,
                    staff_specialty = $12,
                    staff_grade = $13,
                    staff_display_name = $14
                WHERE telegram_id = $1
            """,
                telegram_id,
                first_name,
                last_name,
                username,
                role,
                user.get('company'),
                user.get('email'),
                user.get('phone'),
                user.get('position'),
                user.get('client_status'),
                user.get('cabinet_token'),
                user.get('staff_specialty'),
                user.get('staff_grade'),
                user.get('staff_display_name'),
            )
            print(f"   🔄 Обновлён: {first_name} {last_name} (@{username}) — {role}")
            updated += 1
        else:
            # Создаём нового
            await conn.execute("""
                INSERT INTO users (
                    telegram_id, first_name, last_name, username, role,
                    company, email, phone, position, client_status, cabinet_token,
                    staff_specialty, staff_grade, staff_display_name
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            """,
                telegram_id,
                first_name,
                last_name,
                username,
                role,
                user.get('company'),
                user.get('email'),
                user.get('phone'),
                user.get('position'),
                user.get('client_status'),
                user.get('cabinet_token'),
                user.get('staff_specialty'),
                user.get('staff_grade'),
                user.get('staff_display_name'),
            )
            print(f"   ✅ Создан: {first_name} {last_name} (@{username}) — {role}")
            created += 1
    
    await conn.close()
    
    print(f"\n=== Готово! ===")
    print(f"   Создано: {created}")
    print(f"   Обновлено: {updated}")
    print(f"\n🌐 Откройте http://localhost:8081/login и выберите любого пользователя")


if __name__ == '__main__':
    asyncio.run(main())
