# Деплой мини-приложения на сервер

## Что создано

Все готово для деплоя мини-приложения на ваш сервер:

- **Сервер:** 217.198.13.11
- **Поддомен:** miniapp.rusneurosoft.ru
- **Путь на сервере:** /var/www/nc-miniapp
- **Порт:** 8080
- **SSL:** Let's Encrypt (будет настроен автоматически)

## Структура файлов

```
deploy/
├── docker-compose.miniapp.yml  # Docker Compose для мини-приложения
├── nginx-miniapp.conf          # Конфигурация Nginx
├── deploy.sh                   # Автоматический деплой
├── deploy-manual.sh            # Команды для ручного деплоя
├── DNS_SETUP.md               # Подробная инструкция по DNS
├── MANUAL_DEPLOY.md           # Подробная инструкция по деплою
└── QUICK_DEPLOY.md            # Быстрая инструкция
```

## Шаг 1: Настройка DNS (ОБЯЗАТЕЛЬНО!)

Добавьте DNS запись в панели управления вашего доменного регистратора:

**Для rusneurosoft.ru добавьте:**
- **Тип:** A
- **Имя/Host:** miniapp
- **Значение/IP:** 217.198.13.11
- **TTL:** 3600

### Где добавить?

В зависимости от вашего регистратора:
- **REG.RU:** Личный кабинет → Домены → rusneurosoft.ru → Управление зоной DNS
- **Cloudflare:** Dashboard → DNS → Add record
- **Timeweb/Beget:** Панель управления → DNS/Домены

**ВАЖНО:** Подождите 5-30 минут после добавления DNS записи!

## Шаг 2: Деплой на сервер

### Вариант A: Автоматический деплой (рекомендуется)

```bash
cd /Users/evgenijkukuskin/Documents/Проекты/cursor/NC_bot/deploy
./deploy.sh
```

При запросе пароля введите: `aHVexY2#Da2?Rt`

### Вариант B: Ручной деплой

Если автоматический не работает, следуйте инструкции в `MANUAL_DEPLOY.md`

## Шаг 3: Проверка работы

1. **Проверьте DNS:**
   ```bash
   nslookup miniapp.rusneurosoft.ru
   # Должен вернуть: 217.198.13.11
   ```

2. **Откройте в браузере:**
   - HTTP: http://miniapp.rusneurosoft.ru
   - HTTPS: https://miniapp.rusneurosoft.ru (после настройки SSL)

3. **Проверьте API:**
   ```bash
   curl "https://miniapp.rusneurosoft.ru/api/can-spin?telegram_id=123456"
   ```

## Шаг 4: Обновление бота

В файле `.env` бота обновите:

```env
WEBAPP_URL=https://miniapp.rusneurosoft.ru
```

Затем перезапустите бота:

```bash
cd /path/to/bot
docker-compose restart bot
# или
systemctl restart bot
```

## Финальная ссылка

После успешного деплоя ваше мини-приложение будет доступно по адресу:

**https://miniapp.rusneurosoft.ru**

Эту ссылку нужно использовать в боте для кнопки "🎰 Крутить рулетку призов".

## Полезные команды

### Подключение к серверу:
```bash
ssh root@217.198.13.11
# Пароль: aHVexY2#Da2?Rt
```

### Просмотр логов:
```bash
ssh root@217.198.13.11 "cd /var/www/nc-miniapp && docker-compose logs -f"
```

### Перезапуск контейнера:
```bash
ssh root@217.198.13.11 "cd /var/www/nc-miniapp && docker-compose restart"
```

### Проверка статуса:
```bash
ssh root@217.198.13.11 "cd /var/www/nc-miniapp && docker-compose ps"
```

## Устранение проблем

### DNS не работает
- Подождите дольше (до 1 часа)
- Проверьте правильность добавленной записи
- Попробуйте другой DNS сервер: `nslookup miniapp.rusneurosoft.ru 8.8.8.8`

### Nginx не запускается
```bash
ssh root@217.198.13.11 "nginx -t"
ssh root@217.198.13.11 "systemctl status nginx"
```

### Docker контейнер не запускается
```bash
ssh root@217.198.13.11 "cd /var/www/nc-miniapp && docker-compose logs"
```

### SSL не настраивается
- Убедитесь, что DNS работает
- Проверьте, что порт 80 открыт
- Попробуйте вручную: `certbot --nginx -d miniapp.rusneurosoft.ru`

## Контакты

Если возникли проблемы:
1. Проверьте `MANUAL_DEPLOY.md` для подробной инструкции
2. Проверьте `DNS_SETUP.md` для настройки DNS
3. Проверьте логи на сервере

## Что дальше?

После успешного деплоя:
1. ✅ DNS настроен
2. ✅ Приложение работает
3. ✅ SSL настроен
4. ✅ Бот обновлен с новым WEBAPP_URL
5. ✅ Готово! Пользователи могут крутить рулетку

**Ваша ссылка:** https://miniapp.rusneurosoft.ru
