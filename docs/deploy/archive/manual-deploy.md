# Ручной деплой мини-приложения на сервер

## Шаг 1: Подключение к серверу

```bash
ssh root@217.198.13.11
# Пароль: aHVexY2#Da2?Rt
```

## Шаг 2: Создание папки для проекта

```bash
mkdir -p /var/www/nc-miniapp
cd /var/www/nc-miniapp
```

## Шаг 3: Загрузка файлов

### С локального компьютера:

```bash
# Перейдите в папку проекта на локальном компьютере
cd /Users/evgenijkukuskin/Documents/Проекты/cursor/NC_bot

# Загрузите файлы на сервер
scp -r mini_app root@217.198.13.11:/var/www/nc-miniapp/
scp -r app root@217.198.13.11:/var/www/nc-miniapp/
scp Dockerfile.webapp root@217.198.13.11:/var/www/nc-miniapp/
scp requirements.txt root@217.198.13.11:/var/www/nc-miniapp/
scp .env root@217.198.13.11:/var/www/nc-miniapp/
scp deploy/docker-compose.miniapp.yml root@217.198.13.11:/var/www/nc-miniapp/docker-compose.yml
```

## Шаг 4: Настройка Nginx

### На сервере:

```bash
# Создайте конфигурацию Nginx
cat > /etc/nginx/sites-available/miniapp.neurosoft.pro << 'EOF'
server {
    listen 80;
    server_name miniapp.neurosoft.pro;

    location / {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    location /api/ {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF

# Активируйте конфигурацию
ln -sf /etc/nginx/sites-available/miniapp.neurosoft.pro /etc/nginx/sites-enabled/

# Проверьте конфигурацию
nginx -t

# Перезагрузите Nginx
systemctl reload nginx
```

## Шаг 5: Запуск Docker контейнера

```bash
cd /var/www/nc-miniapp

# Остановите старый контейнер (если есть)
docker-compose down || true

# Соберите образ
docker-compose build

# Запустите контейнер
docker-compose up -d

# Проверьте статус
docker-compose ps

# Посмотрите логи
docker-compose logs -f
```

## Шаг 6: Настройка DNS

Добавьте DNS запись:
- **Тип:** A
- **Имя:** miniapp
- **Значение:** 217.198.13.11

Подождите 5-30 минут для распространения DNS.

## Шаг 7: Установка SSL сертификата

После того как DNS заработает:

```bash
# Установите certbot (если еще не установлен)
apt update
apt install certbot python3-certbot-nginx -y

# Получите SSL сертификат
certbot --nginx -d miniapp.neurosoft.pro --non-interactive --agree-tos --email info@neurosoft.pro
```

## Шаг 8: Проверка работы

1. Откройте в браузере: https://miniapp.neurosoft.pro
2. Должна открыться страница с рулеткой
3. Проверьте API: https://miniapp.neurosoft.pro/api/can-spin?telegram_id=123456

## Шаг 9: Обновление WEBAPP_URL в боте

В файле `.env` бота обновите:

```env
WEBAPP_URL=https://miniapp.neurosoft.pro
```

Перезапустите бота.

## Полезные команды

### Просмотр логов:
```bash
cd /var/www/nc-miniapp
docker-compose logs -f
```

### Перезапуск контейнера:
```bash
cd /var/www/nc-miniapp
docker-compose restart
```

### Остановка контейнера:
```bash
cd /var/www/nc-miniapp
docker-compose down
```

### Обновление кода:
```bash
# С локального компьютера
scp -r mini_app root@217.198.13.11:/var/www/nc-miniapp/

# На сервере
cd /var/www/nc-miniapp
docker-compose restart
```

## Готово!

Ваше мини-приложение доступно по адресу:
**https://miniapp.neurosoft.pro**
