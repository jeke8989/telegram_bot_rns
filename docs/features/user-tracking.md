# 📊 Система отслеживания пользователей

## Описание

Все пользователи, которые взаимодействуют с ботом (отправляют сообщения, нажимают кнопки), **автоматически сохраняются** в таблицу `users` базы данных.

## Как это работает

### Автоматическое сохранение

Бот использует **middleware** (промежуточный обработчик), который перехватывает **каждое** взаимодействие пользователя с ботом:

- ✅ Отправка сообщений
- ✅ Нажатие на кнопки (inline keyboard)
- ✅ Команды (/start, /roulette)
- ✅ Голосовые сообщения
- ✅ Отправка контактов

### Данные, которые сохраняются

```sql
- telegram_id       -- Уникальный ID пользователя в Telegram
- first_name        -- Имя
- last_name         -- Фамилия
- username          -- Username (@username)
- is_bot            -- Это бот? (всегда false для обычных пользователей)
- language_code     -- Язык интерфейса (ru, en)
- is_blocked        -- Пользователь заблокировал бота?
- last_interaction  -- Время последнего взаимодействия
- created_at        -- Время первого взаимодействия
```

### Обновление данных

При каждом взаимодействии:
- Если пользователя **нет в базе** → создается новая запись
- Если пользователь **уже есть** → обновляются `first_name`, `last_name`, `username`, `language_code`, `last_interaction`

## Проверка статистики

### На сервере

```bash
cd /var/www/nc-miniapp
./check_users.sh
```

### Вручную через SQL

```bash
# Подключиться к базе
docker exec -it neuro-connector-db psql -U neuro_user -d neuro_connector

# Посмотреть всех пользователей
SELECT * FROM users ORDER BY last_interaction DESC;

# Количество пользователей
SELECT COUNT(*) FROM users;

# Новые за сегодня
SELECT COUNT(*) FROM users WHERE created_at::date = CURRENT_DATE;

# Активные за последние 7 дней
SELECT COUNT(*) FROM users WHERE last_interaction > NOW() - INTERVAL '7 days';
```

## Использование для рассылок

Таблица `users` специально создана для **broadcast** (массовых рассылок).

### Скрипт рассылки

```bash
cd /var/www/nc-miniapp
python broadcast.py "Ваше сообщение"
```

См. подробности в `BROADCAST.md`

## Структура таблицы

```sql
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    username VARCHAR(255),
    is_bot BOOLEAN DEFAULT FALSE,
    language_code VARCHAR(10),
    is_blocked BOOLEAN DEFAULT FALSE,
    last_interaction TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
)
```

## Важно! 🚨

- **НЕ удаляйте** записи из таблицы `users` вручную
- Поле `is_blocked` обновляется автоматически при ошибках отправки сообщений
- Все пользователи сохраняются **автоматически** - не нужно ничего настраивать

## Проверка работы middleware

В логах бота вы увидите:

```
database - INFO - User 173385085 saved to database
```

Эта запись появляется при **каждом** взаимодействии пользователя с ботом.

## Текущая статистика

```bash
# На сервере запустите:
./check_users.sh
```

Вы увидите:
- Общее количество пользователей
- Новых за 24 часа
- Последних 10 пользователей
- Активных за 7 дней
- Заблокированных

---

**✅ Система работает автоматически! Все пользователи сохраняются без дополнительных действий.**
