#!/usr/bin/env python3
"""
Script to update bot commands in Telegram
"""
import asyncio
import aiohttp
from config import Config

async def update_commands():
    """Update bot commands via Telegram API"""
    config = Config()
    
    commands = [
        {
            "command": "start",
            "description": "🚀 Начать работу с ботом"
        },
        {
            "command": "roulette",
            "description": "🎰 Крутить рулетку призов"
        }
    ]
    
    url = f"https://api.telegram.org/bot{config.telegram_token}/setMyCommands"
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"commands": commands}) as response:
            result = await response.json()
            if result.get("ok"):
                print("✅ Команды бота успешно обновлены!")
                print("\nДоступные команды:")
                for cmd in commands:
                    print(f"  /{cmd['command']} - {cmd['description']}")
            else:
                print(f"❌ Ошибка: {result}")

if __name__ == "__main__":
    asyncio.run(update_commands())
