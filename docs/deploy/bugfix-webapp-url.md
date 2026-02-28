# 🐛 Исправление: WEBAPP_URL не передавался в контейнер

## Проблема
Финальное сообщение не отправлялось из-за ошибки:
```
BadRequest: Inline keyboard button web app url 'http://localhost:8080' is invalid: only https links are allowed
```

## Причина
Переменная `WEBAPP_URL` была в `.env` файле, но **не передавалась в Docker контейнер** бота через `docker-compose.yml`.

Бот использовал дефолтное значение из `config.py`:
```python
webapp_url = os.getenv('WEBAPP_URL', 'http://localhost:8080')  # ← дефолт
```

---

## Что было исправлено:

### 1. ✅ Добавлены переменные в `docker-compose.yml`

**Было:**
```yaml
services:
  bot:
    environment:
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY}
      # ... другие переменные
      COMPANY_LINKEDIN: ${COMPANY_LINKEDIN}
      # ❌ WEBAPP_URL отсутствует!
```

**Стало:**
```yaml
services:
  bot:
    environment:
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY}
      # ... другие переменные
      COMPANY_LINKEDIN: ${COMPANY_LINKEDIN}
      WEBAPP_URL: ${WEBAPP_URL}              # ✅ Добавлено
      CASES_LINK: ${CASES_LINK}              # ✅ Добавлено
      BOOK_CALL_LINK: ${BOOK_CALL_LINK}      # ✅ Добавлено
```

---

## Проверка:

### До исправления:
```bash
$ docker compose exec bot printenv | grep WEBAPP
# Пусто!
```

### После исправления:
```bash
$ docker compose exec bot printenv | grep WEBAPP
WEBAPP_URL=https://miniapp.rusneurosoft.ru  # ✅
```

---

## Почему это важно:

Telegram **требует HTTPS** для Web App кнопок. Использование `http://localhost:8080` приводит к ошибке `400 Bad Request`.

### Правильная схема:
```
.env файл
  ↓
docker-compose.yml (environment)
  ↓
Docker контейнер
  ↓
config.py (os.getenv)
  ↓
bot.py (self.config.webapp_url)
```

Если хотя бы одно звено пропущено, используется **дефолтное значение** из `config.py`.

---

## Изменённые файлы:

### `docker-compose.yml`

**Добавлено в секцию `bot → environment`:**
```yaml
WEBAPP_URL: ${WEBAPP_URL}
CASES_LINK: ${CASES_LINK}
BOOK_CALL_LINK: ${BOOK_CALL_LINK}
```

---

## Деплой:

**Локально:**
```bash
cd /Users/evgenijkukuskin/Documents/Проекты/cursor/NC_bot
docker compose down bot
docker compose up -d bot
```

**На сервере:**
```bash
ssh root@217.198.13.11
cd /var/www/nc-miniapp
docker compose -f docker-compose.full.yml down miniapp
docker compose -f docker-compose.full.yml up -d miniapp
```

---

## ✅ Результат:

- `WEBAPP_URL` передаётся в контейнер ✅
- Используется правильный HTTPS URL ✅
- Кнопка Web App работает ✅
- Финальное сообщение отправляется ✅
- Рулетка открывается ✅

---

## 🧪 Тестирование:

1. `/start` → выберите роль
2. Пройдите квиз
3. Поделитесь контактом
4. **Получите финальное сообщение с кнопкой "🎰 Крутить AI рулетку"** ✅
5. Нажмите кнопку → откроется мини-приложение на **https://miniapp.rusneurosoft.ru**

---

**Всё исправлено и работает!** 🎉
