"""
Configuration module for Neuro-Connector Bot
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Configuration class"""
    
    # Telegram
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    support_group_id = int(os.getenv('SUPPORT_GROUP_ID', '-5136080434'))
    
    # OpenRouter API (для всех AI-интеграций, включая Whisper)
    openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
    openrouter_model = os.getenv('OPENROUTER_MODEL', 'gpt-4o')
    
    # OpenAI API (для Whisper транскрибации)
    openai_api_key = os.getenv('OPENAI_API_KEY', '')
    
    # Mini App Configuration
    webapp_url = os.getenv('WEBAPP_URL', 'http://localhost:8080')
    
    # Database
    database_url = os.getenv('DATABASE_URL')
    postgres_user = os.getenv('POSTGRES_USER')
    postgres_password = os.getenv('POSTGRES_PASSWORD')
    postgres_db = os.getenv('POSTGRES_DB')
    
    # Application
    app_env = os.getenv('APP_ENV', 'development')
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    # Company Information
    company_name = os.getenv('COMPANY_NAME', 'РусНейроСофт')
    company_description = os.getenv('COMPANY_DESCRIPTION', 'Создаем интеллектуальные IT-решения для бизнеса')
    company_email = os.getenv('COMPANY_EMAIL', 'info@rusneurosoft.ru')
    company_telegram = os.getenv('COMPANY_TELEGRAM', '')
    company_website = os.getenv('COMPANY_WEBSITE', 'https://rusneurosoft.ru')
    cases_link = os.getenv('CASES_LINK', 'https://rusneurosoft.ru/cases')
    book_call_link = os.getenv('BOOK_CALL_LINK', 'https://rusneurosoft.ru/book')
    
    def __init__(self):
        """Validate configuration"""
        if not self.telegram_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set in environment variables")
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not set in environment variables")
        if not self.database_url:
            raise ValueError("DATABASE_URL is not set in environment variables")
