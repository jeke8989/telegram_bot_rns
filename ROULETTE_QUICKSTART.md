# 🎰 AI Рулетка - Быстрый старт

## Что это?

Telegram Mini App с интерактивной рулеткой для розыгрыша скидок на разработку от **5,000₽** до **30,000₽**.

## Как использовать

### 1. Запуск

```bash
# Запустить все контейнеры (бот + webapp + database)
docker compose up -d

# Проверить статус
docker compose ps
```

Все три сервиса должны быть в статусе `Up`:
- `neuro-connector-bot` - Telegram бот
- `neuro-connector-webapp` - Веб-сервер Mini App
- `neuro-connector-db` - PostgreSQL

### 2. Доступ к рулетке

**Через бота:**
1. Открыть бота в Telegram
2. Пройти опрос (предприниматель/стартапер/специалист)
3. В финальном сообщении нажать кнопку **"🎰 Крутить рулетку призов"**

**Через команду:**
1. Открыть бота в Telegram
2. Отправить `/roulette`
3. Нажать кнопку **"🎰 Крутить рулетку!"**

### 3. Локальное тестирование

**Проверка API:**
```bash
# Health check
curl http://localhost:8080/api/health
# {"status": "ok"}

# Проверить статус пользователя
curl "http://localhost:8080/api/can-spin?telegram_id=123456789"
# {"can_spin": true, "prize": null}

# Крутить рулетку
curl -X POST http://localhost:8080/api/spin \
  -H "Content-Type: application/json" \
  -d '{"telegram_id": 123456789}'
# {"prize": 15000}
```

**Открыть в браузере:**
```bash
open http://localhost:8080
```

## Конфигурация

### Переменные окружения

Добавить в `.env`:

```env
# URL Mini App (для production замените на ваш домен)
WEBAPP_URL=http://localhost:8080
```

### Призы

По умолчанию: `[5000, 10000, 15000, 20000, 30000]`

Чтобы изменить, отредактируйте:
- `mini_app/server.py` - строка `PRIZES = [...]`
- `mini_app/static/script.js` - строка `const PRIZES = [...]`

### Вероятности

Сейчас: **Равномерное распределение** (каждый приз имеет одинаковый шанс 20%)

Чтобы сделать взвешенное:
```python
# В mini_app/server.py
import random

# Вместо random.choice(PRIZES)
weights = [40, 30, 20, 7, 3]  # %: 40% для 5k, 30% для 10k, и т.д.
prize = random.choices(PRIZES, weights=weights)[0]
```

## База данных

### Таблица roulette_spins

```sql
-- Посмотреть все спины
SELECT * FROM roulette_spins ORDER BY spun_at DESC;

-- Статистика по призам
SELECT 
    prize_amount as "Приз",
    COUNT(*) as "Количество",
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as "Процент"
FROM roulette_spins
GROUP BY prize_amount
ORDER BY prize_amount;

-- Удалить спин пользователя (для повторного теста)
DELETE FROM roulette_spins WHERE telegram_id = 123456789;
```

### Подключение к БД

```bash
docker compose exec postgres psql -U neuro_user -d neuro_connector

# Или через pgAdmin/DBeaver:
# Host: localhost
# Port: 5434
# Database: neuro_connector
# User: neuro_user
# Password: из .env
```

## Логи

```bash
# Все логи
docker compose logs -f

# Только webapp
docker compose logs webapp -f

# Только bot
docker compose logs bot -f

# Последние 50 строк
docker compose logs webapp --tail=50
```

## Остановка

```bash
# Остановить все контейнеры
docker compose down

# Остановить и удалить данные БД
docker compose down -v
```

## Troubleshooting

### Контейнер webapp перезапускается

```bash
# Смотрим логи
docker compose logs webapp

# Часто это из-за переменных окружения
# Проверяем .env файл
```

### Mini App не открывается в Telegram

1. Проверить, что webapp работает:
   ```bash
   curl http://localhost:8080/api/health
   ```

2. Для production нужен HTTPS:
   - Настроить nginx с SSL
   - Или использовать ngrok для тестирования

3. Обновить `WEBAPP_URL` в `.env`

### Повторное тестирование

```bash
# Удалить спин пользователя из БД
docker compose exec postgres psql -U neuro_user -d neuro_connector \
  -c "DELETE FROM roulette_spins WHERE telegram_id = YOUR_TELEGRAM_ID;"
```

## Production Deployment

### 1. Настроить домен и SSL

```bash
# Пример с nginx
server {
    listen 443 ssl;
    server_name roulette.your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 2. Обновить переменные

```env
WEBAPP_URL=https://roulette.your-domain.com
```

### 3. Настроить в BotFather

1. Открыть @BotFather
2. `/setmenubutton`
3. Выбрать вашего бота
4. Указать URL: `https://roulette.your-domain.com`
5. Указать название кнопки: "🎰 Рулетка призов"

## Полезные ссылки

- [Подробная документация](ROULETTE_FEATURE.md)
- [Telegram Mini Apps Docs](https://core.telegram.org/bots/webapps)
- [aiohttp Documentation](https://docs.aiohttp.org/)

---

**Готово!** 🎉 Рулетка работает и готова к использованию!
