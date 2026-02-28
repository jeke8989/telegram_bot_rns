#!/bin/bash
# ============================================================
# Синхронизация данных из prod БД в локальную dev БД
# ============================================================
#
# Использование:
#   ./scripts/sync_prod_to_dev.sh
#
# Требования:
#   - Запущенный dev-контейнер postgres (docker-compose.dev.yml)
#   - SSH-доступ к prod серверу
#   - pg_dump / psql установлены локально (или через docker exec)
# ============================================================

set -euo pipefail

# --- Конфигурация ---
PROD_HOST="${SERVER_HOST:-217.198.13.11}"
PROD_USER="${SERVER_USER:-root}"
PROD_DB_USER="${POSTGRES_USER:-neuro_user}"
PROD_DB_NAME="${POSTGRES_DB:-neuro_connector}"
PROD_CONTAINER="neuro-connector-db"

DEV_CONTAINER="neuro-connector-db-dev"
DEV_DB_USER="neuro_user"
DEV_DB_NAME="neuro_connector"

DUMP_FILE="/tmp/prod_dump_$(date +%Y%m%d_%H%M%S).sql"

echo "=== Синхронизация prod → dev ==="
echo ""

# --- Шаг 1: Дамп из prod ---
echo "[1/4] Создание дампа prod базы на сервере..."
ssh "${PROD_USER}@${PROD_HOST}" \
    "docker exec ${PROD_CONTAINER} pg_dump -U ${PROD_DB_USER} -d ${PROD_DB_NAME} --no-owner --no-acl" \
    > "${DUMP_FILE}"

DUMP_SIZE=$(du -h "${DUMP_FILE}" | cut -f1)
echo "       Дамп создан: ${DUMP_FILE} (${DUMP_SIZE})"

# --- Шаг 2: Проверка dev контейнера ---
echo "[2/4] Проверка dev PostgreSQL..."
if ! docker ps --format '{{.Names}}' | grep -q "^${DEV_CONTAINER}$"; then
    echo "       ОШИБКА: Контейнер ${DEV_CONTAINER} не запущен."
    echo "       Запустите: docker compose -f docker-compose.dev.yml --env-file .env.dev up -d postgres-dev"
    rm -f "${DUMP_FILE}"
    exit 1
fi
echo "       OK — контейнер запущен"

# --- Шаг 3: Очистка dev базы ---
echo "[3/4] Очистка dev базы..."
docker exec -i "${DEV_CONTAINER}" psql -U "${DEV_DB_USER}" -d "${DEV_DB_NAME}" -c "
    DO \$\$
    DECLARE r RECORD;
    BEGIN
        FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
            EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE';
        END LOOP;
    END \$\$;
"
echo "       Таблицы удалены"

# --- Шаг 4: Импорт дампа ---
echo "[4/4] Импорт дампа в dev базу..."
docker exec -i "${DEV_CONTAINER}" psql -U "${DEV_DB_USER}" -d "${DEV_DB_NAME}" < "${DUMP_FILE}"
echo "       Импорт завершён"

# --- Очистка ---
rm -f "${DUMP_FILE}"

echo ""
echo "=== Готово! Dev база синхронизирована с prod ==="
echo ""
echo "Проверить: docker exec -it ${DEV_CONTAINER} psql -U ${DEV_DB_USER} -d ${DEV_DB_NAME} -c '\\dt'"
