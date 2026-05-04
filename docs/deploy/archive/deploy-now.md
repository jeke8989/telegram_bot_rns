# ЗАПУСК ДЕПЛОЯ СЕЙЧАС

## Что нужно сделать (3 простых шага)

### ШАГ 1: Настроить DNS (5 минут)

Зайдите в панель управления вашего регистратора домена neurosoft.pro и добавьте:

```
Тип: A
Имя: miniapp
Значение: 217.198.13.11
TTL: 3600
```

**ВАЖНО:** Подождите 10-15 минут после добавления!

---

### ШАГ 2: Загрузить файлы на сервер (3 минуты)

Откройте терминал и выполните команды:

```bash
# Перейдите в папку проекта
cd /Users/evgenijkukuskin/Documents/Проекты/cursor/NC_bot

# Загрузите файлы (при запросе введите пароль: aHVexY2#Da2?Rt)
scp -r mini_app root@217.198.13.11:/var/www/nc-miniapp/
scp -r app root@217.198.13.11:/var/www/nc-miniapp/
scp Dockerfile.webapp root@217.198.13.11:/var/www/nc-miniapp/
scp requirements.txt root@217.198.13.11:/var/www/nc-miniapp/
scp .env root@217.198.13.11:/var/www/nc-miniapp/
scp deploy/docker-compose.miniapp.yml root@217.198.13.11:/var/www/nc-miniapp/docker-compose.yml
scp deploy/nginx-miniapp.conf root@217.198.13.11:/tmp/miniapp.conf
```

---

### ШАГ 3: Настроить и запустить на сервере (5 минут)

Подключитесь к серверу:

```bash
ssh root@217.198.13.11
# Пароль: aHVexY2#Da2?Rt
```

На сервере выполните:

```bash
# Создайте директорию (если еще не создана)
mkdir -p /var/www/nc-miniapp

# Настройте Nginx
mv /tmp/miniapp.conf /etc/nginx/sites-available/miniapp.neurosoft.pro
ln -sf /etc/nginx/sites-available/miniapp.neurosoft.pro /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# Запустите Docker контейнер
cd /var/www/nc-miniapp
docker-compose down || true
docker-compose build
docker-compose up -d

# Проверьте статус
docker-compose ps
```

Должно показать:
```
NAME         STATUS
nc-miniapp   Up X seconds
```

---

### ШАГ 4: Настроить SSL (2 минуты)

После того как DNS заработает (подождите 10-15 минут после добавления DNS записи):

```bash
# На сервере выполните:
certbot --nginx -d miniapp.neurosoft.pro --non-interactive --agree-tos --email info@neurosoft.pro
```

---

### ШАГ 5: Обновить бот (1 минута)

В файле `/Users/evgenijkukuskin/Documents/Проекты/cursor/NC_bot/.env` обновите:

```env
WEBAPP_URL=https://miniapp.neurosoft.pro
```

Перезапустите бота:

```bash
cd /Users/evgenijkukuskin/Documents/Проекты/cursor/NC_bot
docker-compose restart bot
```

---

## ГОТОВО! 🎉

Ваше мини-приложение доступно по адресу:

**https://miniapp.neurosoft.pro**

Эту ссылку используйте в боте для кнопки "🎰 Крутить рулетку призов".

---

## Проверка работы

1. Откройте в браузере: https://miniapp.neurosoft.pro
   - Должна открыться страница с рулеткой

2. Проверьте API:
   ```bash
   curl "https://miniapp.neurosoft.pro/api/can-spin?telegram_id=123456"
   ```
   - Должен вернуть JSON с данными

3. В боте:
   - Завершите опрос
   - Нажмите кнопку "🎰 Крутить рулетку призов"
   - Должно открыться мини-приложение

---

## Если что-то не работает

### DNS не резолвится
```bash
# Проверьте DNS
nslookup miniapp.neurosoft.pro

# Если не работает, подождите еще 10-20 минут
```

### Контейнер не запускается
```bash
# Посмотрите логи
ssh root@217.198.13.11 "cd /var/www/nc-miniapp && docker-compose logs"
```

### Nginx выдает ошибку
```bash
# Проверьте конфигурацию
ssh root@217.198.13.11 "nginx -t"

# Посмотрите статус
ssh root@217.198.13.11 "systemctl status nginx"
```

---

## Итоговая информация

| Параметр | Значение |
|----------|----------|
| **Сервер** | 217.198.13.11 |
| **Домен** | miniapp.neurosoft.pro |
| **URL** | https://miniapp.neurosoft.pro |
| **Путь на сервере** | /var/www/nc-miniapp |
| **Порт** | 8080 |
| **DNS запись** | A miniapp 217.198.13.11 |
| **WEBAPP_URL** | https://miniapp.neurosoft.pro |

---

Все готово для деплоя! Выполните шаги выше и мини-приложение заработает.
