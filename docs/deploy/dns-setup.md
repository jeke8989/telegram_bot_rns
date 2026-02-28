# Настройка DNS для мини-приложения

## Поддомен: miniapp.rusneurosoft.ru

### DNS запись, которую нужно добавить:

**Тип записи:** A  
**Имя (Name/Host):** `miniapp`  
**Значение (Value/Points to):** `217.198.13.11`  
**TTL:** `3600` (или оставьте по умолчанию)

## Где добавить DNS запись

1. Зайдите в панель управления вашего доменного регистратора (где зарегистрирован rusneurosoft.ru)
2. Найдите раздел DNS Management / DNS Settings / Zone Editor
3. Добавьте новую A запись с параметрами выше

## Примеры для популярных регистраторов:

### REG.RU:
1. Зайдите в личный кабинет
2. Выберите домен rusneurosoft.ru
3. Перейдите в "Управление зоной DNS"
4. Нажмите "Добавить запись"
5. Выберите тип A
6. Введите:
   - Субдомен: `miniapp`
   - IP-адрес: `217.198.13.11`
7. Сохраните

### Cloudflare:
1. Зайдите в панель Cloudflare
2. Выберите домен rusneurosoft.ru
3. Перейдите в DNS
4. Нажмите "Add record"
5. Выберите:
   - Type: A
   - Name: `miniapp`
   - IPv4 address: `217.198.13.11`
   - Proxy status: DNS only (серая облако)
6. Save

### Timeweb / Beget / другие:
1. Зайдите в панель управления хостингом
2. Найдите раздел DNS или Домены
3. Выберите rusneurosoft.ru
4. Добавьте A запись:
   - Имя: `miniapp`
   - IP: `217.198.13.11`

## Проверка DNS

После добавления записи подождите 5-30 минут (время распространения DNS).

Проверить можно командой:
```bash
nslookup miniapp.rusneurosoft.ru
# или
dig miniapp.rusneurosoft.ru
```

Должно вернуть IP: 217.198.13.11

## После настройки DNS

1. Дождитесь распространения DNS (5-30 минут)
2. Откройте в браузере: http://miniapp.rusneurosoft.ru
3. Если работает, запустите скрипт для установки SSL:
   ```bash
   ssh root@217.198.13.11 "sudo certbot --nginx -d miniapp.rusneurosoft.ru"
   ```
4. После этого сайт будет доступен по HTTPS: https://miniapp.rusneurosoft.ru

## Обновление WEBAPP_URL в боте

После успешного деплоя обновите в `.env`:
```
WEBAPP_URL=https://miniapp.rusneurosoft.ru
```

И перезапустите бота.
