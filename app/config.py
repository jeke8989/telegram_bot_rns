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
    
    # Company Information (NO DEFAULTS - ALL FROM ENV)
    company_name = os.getenv('COMPANY_NAME')
    company_description = os.getenv('COMPANY_DESCRIPTION')
    company_email = os.getenv('COMPANY_EMAIL')
    company_phone = os.getenv('COMPANY_PHONE')
    company_telegram = os.getenv('COMPANY_TELEGRAM', '')
    company_website = os.getenv('COMPANY_WEBSITE')
    company_linkedin = os.getenv('COMPANY_LINKEDIN', '')
    cases_link = os.getenv('CASES_LINK')
    jobs_link = os.getenv('JOBS_LINK', '')
    book_call_link = os.getenv('BOOK_CALL_LINK')
    
    # Zoom API
    zoom_account_id = os.getenv('ZOOM_ACCOUNT_ID', '')
    zoom_client_id = os.getenv('ZOOM_CLIENT_ID', '')
    zoom_client_secret = os.getenv('ZOOM_CLIENT_SECRET', '')
    zoom_webhook_secret_token = os.getenv('ZOOM_WEBHOOK_SECRET_TOKEN', '')
    zoom_ws_subscription_id = os.getenv('ZOOM_WS_SUBSCRIPTION_ID', '')
    
    # Lark API
    lark_app_id = os.getenv('LARK_APP_ID', '')
    lark_app_secret = os.getenv('LARK_APP_SECRET', '')
    lark_group_chat_id = os.getenv('LARK_GROUP_CHAT_ID', '')
    
    # Calendly → Telegram notifications
    calendly_notify_chat_id = os.getenv('CALENDLY_NOTIFY_CHAT_ID', '')

    # Staff
    staff_secret_code = os.getenv('STAFF_SECRET_CODE', 'change_staff')

    STAFF_CONTACTS = {
        'black_tie_777': {
            'name': 'Евгений Кукушкин',
            'role': 'CEO (Руководитель)',
            'phone': '+7 (987) 750-30-75',
            'email': 'info@rusneurosoft.ru',
            'telegram': '@black_tie_777',
            'calendly_url': 'https://calendly.com/jeke8989/30min',
        },
        'IT_anasta': {
            'name': 'Анастасия Синькевич',
            'role': 'COO (Руководитель разработки)',
            'phone': '',
            'email': 'info@rusneurosoft.ru',
            'telegram': '@IT_anasta',
            'calendly_url': '',
        },
    }
    
    # Kimai Time Tracking
    kimai_url = os.getenv('KIMAI_URL', '')
    kimai_api_token = os.getenv('KIMAI_API_TOKEN', '')
    
    def __init__(self):
        """Validate configuration"""
        if not self.telegram_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set in environment variables")
        if not self.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is not set in environment variables")
        if not self.database_url:
            raise ValueError("DATABASE_URL is not set in environment variables")
        if not self.company_name:
            raise ValueError("COMPANY_NAME is not set in environment variables")
        if not self.company_email:
            raise ValueError("COMPANY_EMAIL is not set in environment variables")
        if not self.company_website:
            raise ValueError("COMPANY_WEBSITE is not set in environment variables")
        if not self.cases_link:
            raise ValueError("CASES_LINK is not set in environment variables")
        if not self.book_call_link:
            raise ValueError("BOOK_CALL_LINK is not set in environment variables")
