# Быстрая настройка мини-приложения на Vercel

## Что уже сделано:

✅ Создан `vercel.json` - конфигурация для Vercel
✅ Созданы API endpoints в папке `api/`:
   - `api/can-spin.py` - проверка возможности крутки
   - `api/spin.py` - крутка рулетки

## Что нужно сделать:

### 1. Добавить переменную окружения в Vercel

1. Зайдите на https://vercel.com/dashboard
2. Выберите ваш проект `telegrambotrns`
3. Settings → Environment Variables
4. Добавьте:
   - **Name:** `DATABASE_URL`
   - **Value:** ваш PostgreSQL connection string (например: `postgresql://user:password@host:5432/dbname`)

### 2. Обновить WEBAPP_URL в боте

В вашем `.env` файле обновите:

```env
WEBAPP_URL=https://telegrambotrns.vercel.app
```

Затем перезапустите бота.

### 3. Закоммитить и запушить изменения

```bash
git add vercel.json api/ VERCEL_DEPLOY.md QUICK_VERCEL_SETUP.md
git commit -m "Add Vercel configuration for mini app"
git push
```

Vercel автоматически задеплоит новую версию.

**Примечание:** Если статические файлы не загружаются, создайте папку `public/` и скопируйте туда файлы:

```bash
mkdir -p public
cp mini_app/static/* public/
git add public/
git commit -m "Add public folder for static files"
git push
```

### 4. Проверить работу

1. Откройте: https://telegrambotrns.vercel.app/
   - Должна открыться страница с рулеткой

2. В боте:
   - Завершите опрос
   - Нажмите кнопку "🎰 Крутить рулетку призов"
   - Должно открыться мини-приложение

## Если что-то не работает:

1. **Статические файлы не загружаются:**
   - Проверьте логи в Vercel Dashboard → Functions
   - Убедитесь, что файлы в `mini_app/static/` существуют

2. **API не работает:**
   - Проверьте, что `DATABASE_URL` правильно настроен
   - Проверьте логи в Vercel Dashboard → Functions

3. **База данных недоступна:**
   - Убедитесь, что база данных доступна из интернета
   - Проверьте правильность `DATABASE_URL`

## Готово! 🎉

Теперь ваше мини-приложение доступно по адресу:
**https://telegrambotrns.vercel.app/**

Используйте эту ссылку в `WEBAPP_URL` для бота.
