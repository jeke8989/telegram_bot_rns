# Миграция nc-miniapp 217.198.13.11 → 89.124.122.8

Дата выполнения: 2026-05-04. Выполнено автономно через CLI.

## Итог

Всё перенесено идентично, target поднят, валидация пройдена. Осталось переключить DNS — это финальный шаг под контролем человека.

## Что сейчас работает где

| Компонент | Источник `217.198.13.11` (старый прод) | Цель `89.124.122.8` (новый, готов) |
|---|---|---|
| Контейнеры docker | `neuro-connector-bot/db/webapp` запущены | то же, запущены, healthy |
| База `neuro_connector` | 14 MB, 27 таблиц, 1292 web_sessions | 12 MB, 27 таблиц, **row counts идентичны** |
| pgvector extension | установлен | установлен и проверен (`CREATE EXTENSION vector`) |
| nginx + SSL | работает на `miniapp.neurosoft.pro` | nginx настроен, копия LE-сертификата (валиден до **2026-06-27**) |
| Telegram bot token | старый (ротирован Telegram'ом — невалиден) | **новый** `8364761240:AAFCN…kn5zmI` |
| WEBAPP_URL в `.env` | `https://miniapp.neurosoft.pro` | то же |

DNS `miniapp.neurosoft.pro` сейчас → **`217.198.13.11`** (источник). До переключения пользователи попадают на старый webapp, но бот уже работает на новом сервере (т.к. старый токен невалиден).

## Проверка target до cutover (host-header)

```
curl -k --resolve miniapp.neurosoft.pro:443:89.124.122.8 https://miniapp.neurosoft.pro/        # 200
curl -k --resolve miniapp.neurosoft.pro:443:89.124.122.8 https://miniapp.neurosoft.pro/api/can-spin  # 400 telegram_id required (нормально)
```

Bot getMe: `id=8364761240, username=rus_neuro_code_bot, ok=true`.

## Cutover (что делать)

### 1. Переключить A-запись DNS
- Имя: `miniapp` (или `miniapp.neurosoft.pro`)
- Тип: `A`
- Значение: `89.124.122.8`
- TTL: поставить 60–300 на время переключения

После применения:
```
dig +short miniapp.neurosoft.pro   # должен вернуть 89.124.122.8
```

### 2. Проверка боя
- Открыть https://miniapp.neurosoft.pro/ — должна открыться страница (ровно та же, что и на старом сервере)
- Открыть Telegram-бот `@rus_neuro_code_bot`, нажать `/start`, дойти до WebApp — должен открыться mini app
- Логин в кабинет (existing web_session или новый)

### 3. Остановить старый прод (только после успешной проверки)
```bash
ssh root@217.198.13.11
cd /var/www/nc-miniapp
docker compose stop bot webapp     # postgres оставляем как rollback-резерв
docker compose ps
```
**Не удалять** старый сервер минимум 24–48 часов — БД на нём может пригодиться для rollback.

### 4. (опционально) Инкрементально досинхронизировать БД
Если между снятием дампа (15:19 MSK 2026-05-04) и моментом cutover на старом сервере появились новые записи — их нужно перенести. Способ:
```bash
# на ноуте
ssh root@217.198.13.11 'docker exec neuro-connector-db pg_dump -U neuro_user -d neuro_connector -Fc --no-owner --no-acl' > /tmp/late.dump
scp /tmp/late.dump root@89.124.122.8:/root/late.dump
ssh root@89.124.122.8 'cd /var/www/nc-miniapp && docker compose stop bot webapp && \
  docker exec -i neuro-connector-db psql -U neuro_user -d postgres -c "DROP DATABASE neuro_connector WITH (FORCE);" && \
  docker exec -i neuro-connector-db psql -U neuro_user -d postgres -c "CREATE DATABASE neuro_connector;" && \
  docker exec -i neuro-connector-db psql -U neuro_user -d neuro_connector -c "CREATE EXTENSION vector;" && \
  docker exec -i neuro-connector-db pg_restore -U neuro_user -d neuro_connector --no-owner --no-acl < /root/late.dump && \
  docker compose start bot webapp'
```

### 5. Обновить ip в `WEBAPP_URL` если нужно
В `.env` уже `https://miniapp.neurosoft.pro` — после DNS cutover работает автоматически.

### 6. SSL renewal (через 1.5 месяца)
Когда DNS будет указывать на новый сервер, сертификат продлится сам через certbot timer:
```bash
ssh root@89.124.122.8 'certbot renew --dry-run'
```

## Rollback (если что-то сломалось после cutover)

1. Вернуть DNS A-запись на `217.198.13.11`.
2. На источнике поднять `bot`/`webapp`: `cd /var/www/nc-miniapp && docker compose up -d`.
3. **Важно**: в источнике `.env` лежит **старый** Telegram-токен, который Telegram уже аннулировал. Чтобы старый бот заработал — надо вписать в `/var/www/nc-miniapp/.env` новый токен `8364761240:AAFCN…kn5zmI` и перезапустить: `docker compose restart bot`.

## Что осталось на ноуте

`/tmp/nc_mig/snapshot/`:
- `nc-miniapp.tgz` (133M) — снимок проекта на момент 14:03 MSK
- `neuro_connector.dump` (1.7M) — pg_dump custom format
- `letsencrypt.tgz` (15K) — копия LE-каталога для miniapp
- `nginx-miniapp.conf` (3.1K) — nginx site
- `.p_source`, `.p_target`, `.new_bot_token` — пароли/токен (chmod 600). Удалить после успешной верификации:
  ```bash
  shred -u /tmp/nc_mig/.p_* /tmp/nc_mig/.new_bot_token
  ```

На target в `/root/.snapshot/` — те же артефакты, можно удалить после успешной валидации.

## Что НЕ переносилось

На старом сервере живут ещё проекты, которые остались на месте:
- `ai-assistant-chat` (`/opt/ai-assistant-chat`, контейнеры `ai_chat_postgres`, `neurosoft-app-1`)
- `neurosoft.pro` (`/var/www/neurosoft`, systemd `neurosoft.service`)
- `portal.neurosoft.pro` (nginx + LE)
- Хостовый Redis

Их **не трогали**.

## Известные warnings (не блокеры)

- `OPENAI_API_KEY` и `CALENDLY_NOTIFY_CHAT_ID` отсутствуют в `.env` → docker compose выводит warning, контейнер работает (на проде те же warnings были).
- `version: '3.8'` в docker-compose.yml — устарел, можно удалить, но работает.

## Контрольные команды на target

```bash
ssh root@89.124.122.8

cd /var/www/nc-miniapp
docker compose ps                      # все три контейнера Up
docker compose logs -f bot             # хвост логов бота
docker compose logs -f webapp          # хвост webapp
docker exec neuro-connector-db psql -U neuro_user -d neuro_connector -c "\dt"

systemctl status nginx
nginx -t
ufw status
```
