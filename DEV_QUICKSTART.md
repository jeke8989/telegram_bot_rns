# 🚀 Dev-окружение — Быстрый старт

## Запуск за 3 команды

```bash
# 1. Запустить dev-версию (порт 8081)
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d

# 2. Открыть браузер
open http://localhost:8081/login

# 3. Выбрать любого пользователя из списка → Готово!
```

---

## Что это даёт

✅ **Локальная разработка** — изменения не влияют на prod  
✅ **Отдельная БД** — тестовые данные изолированы  
✅ **Без Telegram** — авторизация через переключатель ролей  
✅ **Hot reload** — код обновляется без пересборки  
✅ **Параллельный запуск** — prod на `:8080`, dev на `:8081`

---

## Тестовые пользователи

| Роль | Пользователь | ID |
|------|--------------|-----|
| 🔴 Admin | Админ Тестовый | 1000001 |
| 🔵 Staff | Евгений Разработчик | 1000002 |
| 🔵 Staff | Анастасия PM | 1000003 |
| 🟠 Seller | Сергей Продавец | 1000004 |
| 🟢 User | Клиент Тестовый | 1000005 |
| 🟢 User | Лид Новый | 1000006 |

---

## Полезные команды

```bash
# Логи
docker logs neuro-connector-webapp-dev -f

# Перезапуск
docker compose -f docker-compose.dev.yml restart webapp-dev

# Остановка
docker compose -f docker-compose.dev.yml down

# Полная очистка (БД + volumes)
docker compose -f docker-compose.dev.yml down -v
```

---

📖 **Подробная документация:** [docs/dev/README.md](docs/dev/README.md)
