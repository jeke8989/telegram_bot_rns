# 📢 Система рассылок сообщений

## Обзор

Система рассылок позволяет отправлять сообщения всем пользователям бота. Все пользователи, которые когда-либо запускали бота командой `/start`, автоматически сохраняются в таблицу `users`.

## База данных

### Таблица `users`

Хранит всех пользователей бота для рассылок:

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    username VARCHAR(255),
    is_bot BOOLEAN DEFAULT FALSE,
    language_code VARCHAR(10),
    is_blocked BOOLEAN DEFAULT FALSE,           -- Пользователь заблокировал бота
    last_interaction TIMESTAMP WITH TIME ZONE,  -- Последнее взаимодействие
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Отличие от таблицы `contacts`

- **`users`** - ВСЕ пользователи, которые запустили бота (для рассылок)
- **`contacts`** - Только пользователи, прошедшие опрос и поделившиеся контактами

## Использование скрипта рассылки

### 1. Просмотр статистики пользователей

```bash
# В контейнере
docker compose exec bot python broadcast.py --stats

# Локально (если есть доступ к БД)
python broadcast.py --stats
```

**Вывод:**
```
==================================================
📊 USER STATISTICS
==================================================
Total users: 150
Active users: 142
Blocked users: 8
==================================================
```

### 2. Отправка рассылки

```bash
# В контейнере
docker compose exec bot python broadcast.py "Ваше сообщение здесь"

# С Markdown форматированием
docker compose exec bot python broadcast.py "**Важно!** Новая функция в боте: используйте /roulette"
```

**Процесс:**
1. Скрипт покажет превью сообщения
2. Запросит подтверждение (введите `yes`)
3. Начнет рассылку с отображением прогресса
4. Покажет статистику в конце

**Пример вывода:**
```
==================================================
BROADCAST MESSAGE:
Привет! Попробуйте новую функцию - рулетку призов! Используйте /roulette
==================================================
Are you sure you want to send this message to all users? (yes/no): yes

Starting broadcast to 142 users...
[1/142] Sending to Иван (ID: 123456789)
[2/142] Sending to Мария (ID: 987654321)
...

==================================================
Broadcast completed!
Total users: 142
✅ Successfully sent: 140
❌ Failed: 2
🚫 Blocked: 2
==================================================
```

## Автоматическая обработка блокировок

Если пользователь заблокировал бота, скрипт автоматически:
1. Пометит его как заблокированного в БД (`is_blocked = TRUE`)
2. Не будет пытаться отправлять ему сообщения в будущих рассылках

## API методы для работы с пользователями

### В коде бота (Python)

```python
from database import Database

db = Database(config.database_url)
await db.connect()

# Получить всех активных пользователей
users = await db.get_all_users(exclude_blocked=True)

# Получить статистику
stats = await db.get_users_count()
# Вернет: {'total': 150, 'active': 142, 'blocked': 8}

# Пометить пользователя как заблокированного
await db.mark_user_blocked(telegram_id=123456789)

# Пометить пользователя как активного
await db.mark_user_active(telegram_id=123456789)
```

## SQL запросы для анализа

### Получить список активных пользователей

```sql
SELECT telegram_id, first_name, username, created_at 
FROM users 
WHERE is_blocked = FALSE 
ORDER BY created_at DESC;
```

### Получить пользователей, зарегистрированных за последние 7 дней

```sql
SELECT COUNT(*) as new_users
FROM users
WHERE created_at >= NOW() - INTERVAL '7 days';
```

### Получить пользователей, которые давно не взаимодействовали с ботом

```sql
SELECT telegram_id, first_name, last_interaction
FROM users
WHERE last_interaction < NOW() - INTERVAL '30 days'
AND is_blocked = FALSE
ORDER BY last_interaction ASC;
```

## Лимиты Telegram

- **Скорость отправки:** До 30 сообщений в секунду
- Скрипт автоматически делает задержку 0.05 секунды между сообщениями
- При больших рассылках (1000+ пользователей) процесс может занять несколько минут

## Безопасность

⚠️ **ВАЖНО:**
- Рассылку может запускать только администратор с доступом к серверу
- Всегда проверяйте текст сообщения перед отправкой
- Не отправляйте спам - это может привести к блокировке бота в Telegram

## Примеры использования

### Уведомление о новой функции

```bash
docker compose exec bot python broadcast.py "🎉 Новая функция!\n\nТеперь вы можете крутить рулетку призов и получить скидку на разработку от 5000 до 30000 рублей!\n\nИспользуйте команду /roulette"
```

### Техническое обслуживание

```bash
docker compose exec bot python broadcast.py "⚠️ Внимание!\n\nБот будет недоступен сегодня с 22:00 до 23:00 МСК для технического обслуживания.\n\nПриносим извинения за неудобства."
```

### Анонс мероприятия

```bash
docker compose exec bot python broadcast.py "📅 Приглашаем на наше мероприятие!\n\n**Дата:** 15 февраля 2026\n**Время:** 18:00 МСК\n**Тема:** AI в бизнесе\n\nПодробности: https://neurosoft.pro/event"
```

## Мониторинг

### Проверка последних пользователей

```sql
SELECT telegram_id, first_name, username, created_at
FROM users
ORDER BY created_at DESC
LIMIT 10;
```

### Статистика по языкам

```sql
SELECT language_code, COUNT(*) as users_count
FROM users
WHERE is_blocked = FALSE
GROUP BY language_code
ORDER BY users_count DESC;
```

## Troubleshooting

### Проблема: Пользователи не сохраняются

**Решение:** Убедитесь, что бот запущен и пользователи отправляют команду `/start`

### Проблема: Большое количество заблокированных пользователей

**Решение:** 
- Проверьте, не отправляете ли вы спам
- Убедитесь, что контент рассылок полезен для пользователей
- Рассылайте сообщения не чаще 1-2 раз в неделю

### Проблема: Рассылка не отправляется

**Решение:**
1. Проверьте доступ к базе данных
2. Убедитесь, что токен бота корректен
3. Проверьте логи: `docker compose logs bot`

## Дополнительные возможности

### Планировщик рассылок (TODO)

В будущем можно добавить:
- Отложенные рассылки
- Повторяющиеся рассылки (например, еженедельный дайджест)
- Сегментация пользователей по языку/активности
- A/B тестирование сообщений
- Персонализация сообщений

### Аналитика (TODO)

- Процент открытий сообщений
- CTR по ссылкам
- Конверсия после рассылки
- Динамика роста базы пользователей
