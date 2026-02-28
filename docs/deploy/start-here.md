# 🚀 ЗАПУСК МИНИ-ПРИЛОЖЕНИЯ

DNS добавлен ✅. Теперь загрузите файлы и запустите на сервере.

## Простой деплой (2 команды)

### 1️⃣ Загрузить файлы на сервер

```bash
cd /Users/evgenijkukuskin/Documents/Проекты/cursor/NC_bot/deploy
./upload.sh
```

При запросе пароля введите: `aHVexY2#Da2?Rt`

### 2️⃣ Настроить и запустить на сервере

```bash
./setup-server.sh
```

При запросе пароля введите: `aHVexY2#Da2?Rt`

---

## Проверка DNS (подождите 10-15 минут)

```bash
nslookup miniapp.rusneurosoft.ru
```

Должен вернуть: `217.198.13.11`

---

## После того как DNS заработает

Установите SSL сертификат:

```bash
ssh root@217.198.13.11
# Пароль: aHVexY2#Da2?Rt

certbot --nginx -d miniapp.rusneurosoft.ru --non-interactive --agree-tos --email info@rusneurosoft.ru
```

---

## Обновить WEBAPP_URL в боте

Откройте файл `.env` и обновите:

```env
WEBAPP_URL=https://miniapp.rusneurosoft.ru
```

Перезапустите бота:

```bash
cd /Users/evgenijkukuskin/Documents/Проекты/cursor/NC_bot
docker-compose restart bot
```

---

## Готово! 🎉

Ваша ссылка: **https://miniapp.rusneurosoft.ru**

Откройте в браузере и проверьте, что рулетка работает.

---

## Если что-то не работает

### DNS еще не работает
- Подождите еще 10-20 минут
- Проверьте: `nslookup miniapp.rusneurosoft.ru 8.8.8.8`

### Контейнер не запустился
```bash
ssh root@217.198.13.11 "cd /var/www/nc-miniapp && docker-compose logs"
```

### Nginx выдает ошибку
```bash
ssh root@217.198.13.11 "systemctl status nginx"
```

---

## Проверка работы

1. **DNS:** `nslookup miniapp.rusneurosoft.ru` → 217.198.13.11 ✅
2. **HTTP:** http://miniapp.rusneurosoft.ru → Открывается рулетка ✅
3. **HTTPS:** https://miniapp.rusneurosoft.ru → Открывается рулетка (после SSL) ✅
4. **API:** `curl https://miniapp.rusneurosoft.ru/api/can-spin?telegram_id=123` ✅
5. **Бот:** Кнопка "Крутить рулетку" открывает мини-приложение ✅

Все готово! Выполните команды выше.
