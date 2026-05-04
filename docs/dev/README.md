# Dev-окружение для локальной разработки

## Описание

Dev-окружение позволяет разрабатывать и тестировать изменения локально, не затрагивая production. Главные отличия:

- **Отдельная локальная база данных** — изолирована от prod
- **Dev-авторизация** — переключатель ролей вместо Telegram
- **Отладка** — `DEBUG=True`, `LOG_LEVEL=DEBUG`
- **Порты** — dev на `8081`, prod на `8080` (можно запускать одновременно)

---

## Быстрый старт

```bash
# 1. Запустить dev-окружение
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d

# 2. Проверить логи (опционально)
docker logs neuro-connector-webapp-dev -f

# 3. Открыть dev-версию в браузере
open http://localhost:8081/login
```

На странице `/login` выбираете любого пользователя из списка и заходите с его ролью.

---

## Тестовые пользователи

В dev-базе созданы следующие тестовые пользователи:

| Роль | Имя | Username | Telegram ID |
|------|-----|----------|-------------|
| **admin** | Админ Тестовый | `@admin_test` | 1000001 |
| **staff** | Евгений Разработчик | `@staff_dev` | 1000002 |
| **staff** | Анастасия PM | `@staff_pm` | 1000003 |
| **seller** | Сергей Продавец | `@seller_test` | 1000004 |
| **user** | Клиент Тестовый | `@user_test` | 1000005 |
| **user** | Лид Новый | `@user_lead` | 1000006 |

---

## Dev-авторизация

В dev-режиме (`APP_ENV=development`) страница `/login` показывает:

- Оранжевый бейдж **DEV MODE**
- Табы для фильтрации по ролям (Все / Admin / Staff / Seller / User)
- Список пользователей с аватарками и ролями
- Клик по пользователю → мгновенная авторизация (без Telegram)

### Как это работает

1. Frontend проверяет доступность эндпоинта `GET /api/auth/dev-users`
2. Если эндпоинт отвечает (только в dev) → показывается dev-логин
3. При клике на пользователя отправляется `POST /api/auth/dev-login` с `telegram_id`
4. Сервер создаёт сессию на 24 часа и редиректит по роли

На production (`APP_ENV=production`) оба эндпоинта возвращают 404 — работает только стандартный Telegram-логин.

---

## Структура файлов

```
NC_bot/
├── .env.dev                    # Dev-конфигурация (в .gitignore)
├── docker-compose.dev.yml      # Dev-инфраструктура
├── scripts/
│   ├── sync_prod_to_dev.sh     # Копирование данных из prod (требует SSH)
│   └── create_dev_users.py     # Создание тестовых пользователей
└── docs/
    └── dev/
        └── README.md           # Эта документация
```

---

## Копирование данных из prod

Если нужны реальные данные из production:

```bash
# Требует SSH-доступ к серверу
./scripts/sync_prod_to_dev.sh
```

Скрипт:
1. Создаёт дамп prod-базы через SSH
2. Очищает dev-базу
3. Импортирует дамп

**Внимание:** скрипт полностью заменяет dev-базу на копию prod.

---

## Создание дополнительных тестовых пользователей

### Вариант 1: Через SQL

```bash
docker exec -i neuro-connector-db-dev psql -U neuro_user -d neuro_connector << 'EOF'
INSERT INTO users (telegram_id, first_name, last_name, username, role) 
VALUES (1000007, 'Новый', 'Пользователь', 'new_user', 'staff')
ON CONFLICT (telegram_id) DO NOTHING;
EOF
```

### Вариант 2: Через webapp API

Если пользователь уже есть в базе, можно просто обновить его роль:

```bash
curl -X PUT http://localhost:8081/api/users/1000007/role \
  -H "Content-Type: application/json" \
  -b "session_token=YOUR_SESSION_TOKEN" \
  -d '{"role": "admin"}'
```

---

## Остановка и очистка

```bash
# Остановить контейнеры (данные сохраняются)
docker compose -f docker-compose.dev.yml --env-file .env.dev down

# Остановить + удалить volumes (полная очистка)
docker compose -f docker-compose.dev.yml --env-file .env.dev down -v
```

---

## Порты

| Сервис | Prod | Dev |
|--------|------|-----|
| WebApp | 8080 | 8081 |
| PostgreSQL | 5434 | 5435 |

Можно запускать prod и dev одновременно — они не конфликтуют.

---

## Переменные окружения

Основные отличия `.env.dev` от `.env`:

```bash
APP_ENV=development        # вместо production
DEBUG=True                 # вместо False
LOG_LEVEL=DEBUG            # вместо INFO
WEBAPP_URL=http://localhost:8081  # вместо https://portal.neurosoft.pro
DATABASE_URL=...postgres-dev...   # вместо postgres
```

---

## Troubleshooting

### Порт 8081 уже занят

```bash
# Найти процесс
lsof -ti:8081

# Убить процесс
kill -9 $(lsof -ti:8081)
```

### База не инициализирована

```bash
# Проверить логи webapp
docker logs neuro-connector-webapp-dev

# Если ошибка подключения к БД — проверить postgres
docker logs neuro-connector-db-dev
```

### Dev-авторизация не работает

Проверьте что:
1. `APP_ENV=development` в `.env.dev`
2. WebApp перезапущен после изменения конфига
3. В базе есть пользователи с `telegram_id IS NOT NULL`

```bash
# Проверить пользователей
docker exec -i neuro-connector-db-dev psql -U neuro_user -d neuro_connector -c \
  "SELECT telegram_id, first_name, role FROM users WHERE telegram_id IS NOT NULL;"
```

---

## Полезные команды

```bash
# Логи webapp (следить в реальном времени)
docker logs neuro-connector-webapp-dev -f

# Подключиться к dev БД
docker exec -it neuro-connector-db-dev psql -U neuro_user -d neuro_connector

# Перезапустить только webapp (после изменения кода)
docker compose -f docker-compose.dev.yml --env-file .env.dev restart webapp-dev

# Статус всех контейнеров
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

---

## Что дальше?

- Изменения в `mini_app/` и `app/` автоматически подхватываются через volume mounts
- После правок перезапустите webapp: `docker compose -f docker-compose.dev.yml restart webapp-dev`
- Для тестирования разных ролей просто перелогиньтесь через `/login`
