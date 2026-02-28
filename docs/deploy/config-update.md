# ✅ Исправление захардкоженных ссылок и контактов

## Проблема
В коде были захардкожены (жестко прописаны) ссылки на сайт компании и контакты вместо использования переменных из `.env`.

## Что исправлено:

### 1. ✅ Добавлена переменная `COMPANY_PHONE` в конфиг

**app/config.py:**
```python
company_phone = os.getenv('COMPANY_PHONE', '+7 (987) 750-30-75')
```

**В .env:**
```
COMPANY_PHONE=+7 (987) 750-30-75
```

### 2. ✅ Исправлена захардкоженная ссылка на Calendly

**Было:**
```python
[InlineKeyboardButton("🗓 Запланировать звонок", url="https://calendly.com/rusneurosoft")]
```

**Стало:**
```python
[InlineKeyboardButton("🗓 Запланировать звонок", url=self.config.book_call_link)]
```

### 3. ✅ Обновлен конфиг с правильными ссылками

**app/config.py:**
```python
cases_link = os.getenv('CASES_LINK', 'https://rusneurosoft.ru/cases')
book_call_link = os.getenv('BOOK_CALL_LINK', 'https://calendly.com/rusneurosoft')
```

### 4. ✅ Добавлены переменные в `.env`

```env
# Company Information
COMPANY_NAME=neuro-code.com
COMPANY_DESCRIPTION=Создаем интеллектуальные IT-решения для бизнеса
COMPANY_EMAIL=info@neuro-code.com
COMPANY_PHONE=+7 (987) 750-30-75
COMPANY_TELEGRAM=@black_tie_777
COMPANY_WEBSITE=https://neuro-code.com
COMPANY_LINKEDIN=https://linkedin.com/company/neuro-code

# Links
CASES_LINK=https://neuro-code.com/cases
BOOK_CALL_LINK=https://calendly.com/neuro-code
```

---

## Теперь все ссылки и контакты управляются из `.env`

### Доступные переменные конфига:

| Переменная | Где используется | Пример |
|------------|------------------|--------|
| `COMPANY_NAME` | Название компании в сообщениях | `neuro-code.com` |
| `COMPANY_DESCRIPTION` | Описание компании | `Создаем интеллектуальные IT-решения` |
| `COMPANY_EMAIL` | Email в контактах | `info@neuro-code.com` |
| `COMPANY_PHONE` | Телефон в контактах | `+7 (987) 750-30-75` |
| `COMPANY_TELEGRAM` | Telegram аккаунт | `@black_tie_777` |
| `COMPANY_WEBSITE` | Сайт компании | `https://neuro-code.com` |
| `COMPANY_LINKEDIN` | LinkedIn профиль | `https://linkedin.com/company/neuro-code` |
| `CASES_LINK` | Ссылка на кейсы | `https://neuro-code.com/cases` |
| `BOOK_CALL_LINK` | Ссылка на запись звонка | `https://calendly.com/neuro-code` |

---

## Как использовать в коде:

### В боте:
```python
# Получить доступ к конфигу
self.config.company_name      # neuro-code.com
self.config.company_email     # info@neuro-code.com
self.config.company_phone     # +7 (987) 750-30-75
self.config.company_website   # https://neuro-code.com
self.config.cases_link        # https://neuro-code.com/cases
self.config.book_call_link    # https://calendly.com/neuro-code
```

### В мини-приложении:
```python
from app.config import Config
config = Config()

config.company_name
config.company_email
config.company_phone
```

---

## Изменённые файлы:

1. ✅ `app/config.py` - добавлена переменная `company_phone`, обновлён `book_call_link`
2. ✅ `app/bot.py` - заменена захардкоженная ссылка на `self.config.book_call_link`
3. ✅ `.env` - добавлены переменные `CASES_LINK` и `BOOK_CALL_LINK`

---

## Деплой:

Файлы загружены на сервер и контейнеры перезапущены:

✅ **Локальный бот:** Перезапущен  
✅ **Удалённое мини-приложение:** Перезапущено  
✅ **Конфигурация:** Обновлена на сервере  

---

## Проверка:

Теперь при изменении контактов компании достаточно обновить только `.env` файл и перезапустить контейнеры:

```bash
# Локально
docker compose restart bot

# На сервере
ssh root@217.198.13.11
cd /var/www/nc-miniapp
docker compose -f docker-compose.full.yml restart miniapp
```

**Никаких захардкоженных ссылок больше нет!** ✅
