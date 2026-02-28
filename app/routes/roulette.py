"""Roulette spin routes."""

import random
import logging
import aiohttp
from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)

PRIZES = [5000, 10000, 15000, 20000, 25000, 30000]


@routes.get('/api/can-spin')
async def can_spin(request):
    try:
        telegram_id = request.query.get('telegram_id')
        if not telegram_id:
            return web.json_response({'error': 'telegram_id required'}, status=400)
        telegram_id = int(telegram_id)
        db = request.app['db']
        can = await db.can_spin_roulette(telegram_id)
        prize = await db.get_user_prize(telegram_id) if not can else None
        return web.json_response({'can_spin': can, 'prize': prize})
    except Exception as e:
        logger.error(f"Error in can-spin endpoint: {e}")
        return web.json_response({'error': str(e)}, status=500)


@routes.post('/api/spin')
async def spin_roulette(request):
    try:
        data = await request.json()
        telegram_id = data.get('telegram_id')
        if not telegram_id:
            return web.json_response({'error': 'telegram_id required'}, status=400)
        telegram_id = int(telegram_id)
        db = request.app['db']
        config = request.app['config']

        if not await db.can_spin_roulette(telegram_id):
            prize = await db.get_user_prize(telegram_id)
            return web.json_response({'error': 'Already spun', 'prize': prize}, status=400)

        prize = random.choice(PRIZES)
        await db.save_roulette_spin(telegram_id, prize)
        logger.info(f"User {telegram_id} won {prize} RUB")

        message_text = (
            f"\U0001f389 **Поздравляем!**\n\n"
            f"Вы выиграли скидку **{prize:,} ₽** на услуги нашей компании!\n\n"
            f"\U0001f4b0 Эта сумма будет вычтена из стоимости разработки вашего проекта.\n\n"
            f"\U0001f4de Свяжитесь с нами, чтобы использовать скидку:\n"
            f"• Сайт: {config.company_website}\n"
            f"• Email: {config.company_email}\n"
            f"• Телефон: {config.company_phone}\n\n"
            f"Спасибо за участие! \U0001f680"
        )
        try:
            url = f"https://api.telegram.org/bot{config.telegram_token}/sendMessage"
            async with aiohttp.ClientSession() as session:
                await session.post(url, json={
                    'chat_id': telegram_id,
                    'text': message_text,
                    'parse_mode': 'Markdown',
                })
        except Exception:
            pass

        return web.json_response({'prize': prize})
    except Exception as e:
        logger.error(f"Error in spin endpoint: {e}")
        return web.json_response({'error': str(e)}, status=500)


@routes.get('/api/health')
async def health(request):
    return web.json_response({'status': 'ok'})
