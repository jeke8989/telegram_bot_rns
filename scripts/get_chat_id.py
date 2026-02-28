#!/usr/bin/env python3
"""
Скрипт для получения ID чата/группы
Запустите бота, добавьте его в группу и отправьте любое сообщение в группу
"""

from config import Config
import requests

config = Config()

# Получаем последние обновления
url = f'https://api.telegram.org/bot{config.telegram_token}/getUpdates'
response = requests.get(url)
result = response.json()

if result.get('ok'):
    updates = result.get('result', [])
    
    if updates:
        print("=" * 50)
        print("ДОСТУПНЫЕ ЧАТЫ:")
        print("=" * 50)
        
        seen_chats = set()
        
        for update in updates[-10:]:  # Последние 10 обновлений
            message = update.get('message') or update.get('my_chat_member')
            
            if message:
                chat = message.get('chat')
                if chat:
                    chat_id = chat.get('id')
                    chat_type = chat.get('type')
                    chat_title = chat.get('title', chat.get('first_name', 'Unknown'))
                    
                    if chat_id not in seen_chats:
                        seen_chats.add(chat_id)
                        print(f"\n📍 {chat_title}")
                        print(f"   ID: {chat_id}")
                        print(f"   Тип: {chat_type}")
        
        print("\n" + "=" * 50)
        print("\n💡 Скопируйте нужный ID и добавьте в .env файл:")
        print("   SUPPORT_GROUP_ID=<ваш_id>")
        print("=" * 50)
    else:
        print("⚠️ Нет недавних сообщений.")
        print("Отправьте любое сообщение в группу, куда добавлен бот.")
else:
    print(f"❌ Ошибка: {result}")
