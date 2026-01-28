#!/usr/bin/env python3
"""
Telegram Bot "Neuro-Connector" v3
Многоуровневая система нетворкинга для конференций
"""

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from telegram.constants import ChatAction
import asyncio
import tempfile
from pathlib import Path
from database import Database
from ai_analyzer import AIAnalyzer
from config import Config

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for ConversationHandler
ROLE_SELECTION = 0
ENTREPRENEUR_Q1 = 1
ENTREPRENEUR_Q2 = 2
ENTREPRENEUR_Q3 = 3
ENTREPRENEUR_Q4 = 4
STARTUPPER_Q1 = 6
STARTUPPER_Q2 = 7
STARTUPPER_Q3 = 8
STARTUPPER_Q4 = 9
SPECIALIST_Q1 = 11
SPECIALIST_Q2 = 12
SPECIALIST_Q3 = 13
SPECIALIST_Q4 = 14
RESEARCHER = 16
CONTACT_SUPPORT = 17

class NeuroConnectorBot:
    def __init__(self):
        self.config = Config()
        self.db = Database(self.config.database_url)
        self.ai = AIAnalyzer(
            openrouter_key=self.config.openrouter_api_key,
            model=self.config.openrouter_model,
            config=self.config
        )
        self._db_initialized = False
    
    async def initialize_db(self):
        """Initialize database connection"""
        if not self._db_initialized:
            await self.db.connect()
            self._db_initialized = True
            logger.info("Database connection initialized")
    
    def get_message_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        """Get text from either text message or voice transcription"""
        # If it's a voice message, get transcription from context
        if update.message.voice:
            text = context.user_data.get('voice_transcription', '')
            # Clear the transcription after using it
            if 'voice_transcription' in context.user_data:
                del context.user_data['voice_transcription']
            return text
        # Otherwise, get text from the message
        return update.message.text if update.message.text else ''
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command - show role selection"""
        user = update.effective_user
        logger.info(f"User {user.id} started the bot")
        
        # Save user to database
        await self.db.save_user(
            telegram_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            language_code=user.language_code
        )
        
        welcome_text = f"""
🤖 **Привет! Я — AI-бот от {self.config.company_name}**

Я анализирую вашу проблему и **предложу конкретное решение** за 2 минуты.

🎯 Отвечу на 3-4 вопроса
🧠 Проанализирую вашу ситуацию
✨ Подготовлю персональные рекомендации

**🎰 Бонус:** В конце вас ждёт сюрприз — рулетка с реальным денежным призом до **30 000 ₽** на услуги нашей компании!

Выберите, что вам ближе:
        """
        
        keyboard = [
            [InlineKeyboardButton("🚀 У меня есть бизнес", callback_data="role_entrepreneur")],
            [InlineKeyboardButton("💡 У меня есть идея/стартап", callback_data="role_startupper")],
            [InlineKeyboardButton("💻 Я разработчик/специалист", callback_data="role_specialist")],
            [InlineKeyboardButton("📈 Ищу интересный проект", callback_data="role_researcher")],
            [InlineKeyboardButton("💬 Связаться с сотрудником", callback_data="contact_support")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        return ROLE_SELECTION

    async def role_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle role selection"""
        query = update.callback_query
        await query.answer()
        
        role = query.data.replace("role_", "")
        user_id = query.from_user.id
        
        # Save role to context
        context.user_data['role'] = role
        context.user_data['user_id'] = user_id
        
        if role == "entrepreneur":
            return await self.entrepreneur_q1(update, context)
        elif role == "startupper":
            return await self.startupper_q1(update, context)
        elif role == "specialist":
            return await self.specialist_q1(update, context)
        elif role == "researcher":
            return await self.researcher_path(update, context)

    # ============= ENTREPRENEUR PATH =============
    async def entrepreneur_q1(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Entrepreneur: Question 1 - Process pain"""
        query = update.callback_query
        
        text = """
📊 **Шаг 1/4: Пожиратель времени.**

Какой **ОДИН рутинный процесс** отнимает у ваших сотрудников 
больше всего времени и сил?

_(например: обработка заявок, подготовка отчетов, 
ответы на однотипные вопросы клиентов, согласование документов)_

💡 *Можете ответить текстом или 🎙️ голосовым сообщением*
        """
        
        keyboard = [
            [InlineKeyboardButton("📝 Обработка заявок", callback_data="pain_requests")],
            [InlineKeyboardButton("📊 Подготовка отчетов", callback_data="pain_reports")],
            [InlineKeyboardButton("💬 Ответы клиентам", callback_data="pain_support")],
            [InlineKeyboardButton("✍️ Написать свой вариант", callback_data="pain_custom")],
            [InlineKeyboardButton("◀️ Назад к выбору роли", callback_data="back_to_roles")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
        return ENTREPRENEUR_Q1

    async def entrepreneur_q1_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button click for Q1"""
        query = update.callback_query
        await query.answer()
        
        choice = query.data.replace("pain_", "")
        
        if choice == "custom":
            # User wants to write custom answer
            await query.edit_message_text(
                text="""
📊 **Шаг 1/4: Пожиратель времени.**

Напишите, какой процесс отнимает больше всего времени:

💡 *Можете ответить текстом или 🎙️ голосовым сообщением*
                """,
                parse_mode='Markdown'
            )
            return ENTREPRENEUR_Q1
        else:
            # Use predefined answer
            pain_map = {
                "requests": "Обработка заявок",
                "reports": "Подготовка отчетов",
                "support": "Ответы на однотипные вопросы клиентов"
            }
            context.user_data['process_pain'] = pain_map.get(choice, "Рутинный процесс")
            
            # Move to Q2
            keyboard = [
                [InlineKeyboardButton("До 10 часов", callback_data="time_0-10")],
                [InlineKeyboardButton("10-30 часов", callback_data="time_10-30")],
                [InlineKeyboardButton("Больше 30 часов", callback_data="time_30+")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text="""
⏱️ **Шаг 2/4: Масштаб проблемы.**

Как бы вы оценили, сколько **рабочих часов в неделю** 
вся команда тратит на этот процесс?
                """,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return ENTREPRENEUR_Q2
    
    async def entrepreneur_q1_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save Q1 answer and move to Q2"""
        context.user_data['process_pain'] = self.get_message_text(update, context)
        
        keyboard = [
            [InlineKeyboardButton("До 10 часов", callback_data="time_0-10")],
            [InlineKeyboardButton("10-30 часов", callback_data="time_10-30")],
            [InlineKeyboardButton("Больше 30 часов", callback_data="time_30+")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_entrepreneur_q1")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text="""
⏱️ **Шаг 2/4: Масштаб проблемы.**

Как бы вы оценили, сколько **рабочих часов в неделю** 
вся команда тратит на этот процесс?
            """,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return ENTREPRENEUR_Q2

    async def entrepreneur_q2_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save Q2 answer and move to Q3"""
        query = update.callback_query
        await query.answer()
        
        time_lost = query.data.replace("time_", "")
        context.user_data['time_lost'] = time_lost
        
        keyboard = [
            [InlineKeyboardButton("💼 Отдел продаж", callback_data="dept_sales")],
            [InlineKeyboardButton("📞 Поддержка клиентов", callback_data="dept_support")],
            [InlineKeyboardButton("💰 Бухгалтерия", callback_data="dept_accounting")],
            [InlineKeyboardButton("🚚 Логистика", callback_data="dept_logistics")],
            [InlineKeyboardButton("✍️ Написать свой вариант", callback_data="dept_custom")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_entrepreneur_q2")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="""
🏢 **Шаг 3/4: Эпицентр рутины.**

Какой **отдел** или какая **роль** в компании больше всего страдает 
от этой задачи?

💡 *Можете выбрать вариант или написать свой*
            """,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return ENTREPRENEUR_Q3

    async def entrepreneur_q3_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button click for Q3 department"""
        query = update.callback_query
        await query.answer()
        
        choice = query.data.replace("dept_", "")
        
        if choice == "custom":
            await query.edit_message_text(
                text="""
🏢 **Шаг 3/4: Эпицентр рутины.**

Какой **отдел** или какая **роль** в компании больше всего страдает 
от этой задачи?

💡 *Можете ответить текстом или 🎙️ голосовым сообщением*
                """,
                parse_mode='Markdown'
            )
            return ENTREPRENEUR_Q3
        else:
            dept_map = {
                "sales": "Отдел продаж",
                "support": "Поддержка клиентов",
                "accounting": "Бухгалтерия",
                "logistics": "Логистика"
            }
            context.user_data['department_affected'] = dept_map.get(choice, "Отдел")
            
            # First send inline keyboard with back button
            inline_keyboard = [
                [InlineKeyboardButton("◀️ Назад", callback_data="back_entrepreneur_q3")]
            ]
            inline_markup = InlineKeyboardMarkup(inline_keyboard)
            
            await query.edit_message_text(
                text=f"""
🤝 **Шаг 4/4: Поиск решения!**

Спасибо! Я вижу узкое место в **{context.user_data['department_affected']}**, 
которое съедает **{context.user_data['time_lost']}** в неделю.

Готовлю для вас конкретную идею по автоматизации этого процесса.

Куда отправить решение и как к вам обращаться?
                """,
                reply_markup=inline_markup,
                parse_mode='Markdown'
            )
            
            # Then send reply keyboard for contact
            contact_keyboard = [
                [KeyboardButton("📲 Поделиться контактом", request_contact=True)],
                [KeyboardButton("✍️ Написать свои контакты")]
            ]
            contact_markup = ReplyKeyboardMarkup(contact_keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await query.message.reply_text(
                "Выберите удобный способ:",
                reply_markup=contact_markup
            )
            return ENTREPRENEUR_Q4
    
    async def entrepreneur_q3_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save Q3 answer and move to Q4"""
        context.user_data['department_affected'] = self.get_message_text(update, context)
        
        # First send inline keyboard with back button
        inline_keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="back_entrepreneur_q3")]
        ]
        inline_markup = InlineKeyboardMarkup(inline_keyboard)
        
        await update.message.reply_text(
            text=f"""
🤝 **Шаг 4/4: Поиск решения!**

Спасибо! Я вижу узкое место в **{context.user_data['department_affected']}**, 
которое съедает **{context.user_data['time_lost']}** в неделю.

Готовлю для вас конкретную идею по автоматизации этого процесса.

Куда отправить решение и как к вам обращаться?
            """,
            reply_markup=inline_markup,
            parse_mode='Markdown'
        )
        
        # Then send reply keyboard for contact
        contact_keyboard = [
            [KeyboardButton("📲 Поделиться контактом", request_contact=True)],
            [KeyboardButton("✍️ Написать свои контакты")]
        ]
        contact_markup = ReplyKeyboardMarkup(contact_keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            "Выберите удобный способ:",
            reply_markup=contact_markup
        )
        return ENTREPRENEUR_Q4

    async def entrepreneur_q4_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact sharing"""
        user_id = context.user_data['user_id']
        
        # Get contact information
        if update.message.contact:
            # User shared contact via button
            phone = update.message.contact.phone_number
            first_name = update.message.contact.first_name
            context.user_data['phone'] = phone
            await update.message.reply_text(
                f"✅ Спасибо, {first_name}! Контакт получен.",
                reply_markup=ReplyKeyboardRemove()
            )
        elif update.message.text and update.message.text == "✍️ Написать свои контакты":
            # User wants to write contact manually
            await update.message.reply_text(
                "📝 Напишите ваши контактные данные (имя, телефон, email):",
                reply_markup=ReplyKeyboardRemove()
            )
            return ENTREPRENEUR_Q4
        elif update.message.text:
            # User provided contact as text
            phone = update.message.text
            context.user_data['phone'] = phone
            await update.message.reply_text(
                "✅ Спасибо! Контакт получен.",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            phone = "Not provided"
            context.user_data['phone'] = phone
        
        # Send notification to support group IMMEDIATELY after contact received
        await self.send_new_lead_notification(
            user_id=user_id,
            user_name=update.effective_user.first_name,
            role='entrepreneur',
            context=context
        )
        
        # Save basic profile to database
        await self.db.save_entrepreneur_profile(
            user_id=user_id,
            process_pain=context.user_data['process_pain'],
            time_lost=context.user_data['time_lost'],
            department_affected=context.user_data['department_affected'],
            phone=context.user_data.get('phone', 'Not provided'),
            email=update.effective_user.username
        )
        
        # Generate solution
        try:
            loading_msg = await update.message.reply_text("⏳ Анализирую вашу проблему и готовлю решение...")
            
            logger.info(f"Generating solution for user {user_id}")
            solution = await self.ai.generate_entrepreneur_solution(
                process_pain=context.user_data['process_pain'],
                time_lost=context.user_data['time_lost'],
                department_affected=context.user_data['department_affected']
            )
            logger.info(f"Solution generated successfully for user {user_id}")
            
            await loading_msg.edit_text("✅ Решение готово!")
            
            # Send business card
            await self.send_business_card(update.message.chat_id, context)
        except Exception as e:
            logger.error(f"Error generating solution for user {user_id}: {e}")
            await update.message.reply_text("❌ Произошла ошибка при генерации решения. Попробуйте позже.")
            return ROLE_SELECTION
        
        # Send solution
        result_text = f"""
✅ <b>Готово, {update.effective_user.first_name}! Все данные сохранены.</b>

🌐 <b>{self.config.company_website}</b>

📊 <b>ПРОБЛЕМА:</b>
Ваш {context.user_data['department_affected']} тратит около <b>{context.user_data['time_lost']}</b> на <b>{context.user_data['process_pain']}</b>.

✨ <b>РЕШЕНИЕ:</b>
{solution}

Мы в <b>{self.config.company_name}</b> успешно решаем именно такие задачи. 
Будем рады обсудить детали и показать кейсы похожих компаний.

Хорошего дня и продуктивной работы! 🚀
        """
        
        keyboard = [
            [InlineKeyboardButton("🎰 Крутить AI рулетку", web_app=WebAppInfo(url=self.config.webapp_url))]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"Sending entrepreneur solution message to user {user_id}")
        try:
            await update.message.reply_text(result_text, reply_markup=reply_markup, parse_mode='HTML')
            logger.info(f"Entrepreneur solution message sent successfully to user {user_id}")
        except Exception as e:
            logger.error(f"Error sending solution message: {e}")
            # Try without formatting if HTML fails
            simple_text = f"✅ Готово! Решение готово.\n\n{solution}\n\nСвяжитесь с нами: {self.config.company_website}"
            await update.message.reply_text(simple_text, reply_markup=reply_markup)
        
        return ROLE_SELECTION
    
    # ============= STARTUPPER PATH =============
    async def startupper_q1(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Startupper: Question 1 - Problem"""
        query = update.callback_query
        
        keyboard = [
            [InlineKeyboardButton("◀️ Назад к выбору роли", callback_data="back_to_roles")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(
                text="""
💡 **Шаг 1/3: Суть идеи.**

В двух словах, какую **ПРОБЛЕМУ** решает ваша идея? Для кого она?

_(Например: "Приложение для поиска напарников для тренировок" 
или "Сервис для автоматизации бухгалтерии фрилансеров")_

💡 *Можете ответить текстом или 🎙️ голосовым сообщением*
                """,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        return STARTUPPER_Q1

    async def startupper_q1_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save Q1 answer and move to Q2"""
        context.user_data['problem_solved'] = self.get_message_text(update, context)
        
        keyboard = [
            [InlineKeyboardButton("Только идея", callback_data="stage_idea")],
            [InlineKeyboardButton("Есть прототип", callback_data="stage_prototype")],
            [InlineKeyboardButton("Первые клиенты", callback_data="stage_clients")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_startupper_q1")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text="""
🎯 **Шаг 2/3: Текущий этап.**

На каком вы сейчас этапе?
            """,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return STARTUPPER_Q2

    async def startupper_q2_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save Q2 answer and move to Q3"""
        query = update.callback_query
        await query.answer()
        
        stage = query.data.replace("stage_", "")
        context.user_data['current_stage'] = stage
        
        keyboard = [
            [InlineKeyboardButton("👨‍💻 Нехватка разработчиков", callback_data="barrier_tech")],
            [InlineKeyboardButton("🎯 Нет понимания MVP", callback_data="barrier_mvp")],
            [InlineKeyboardButton("🎨 Нужен дизайн", callback_data="barrier_design")],
            [InlineKeyboardButton("💰 Нет денег на маркетинг", callback_data="barrier_marketing")],
            [InlineKeyboardButton("✍️ Написать свой вариант", callback_data="barrier_custom")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_startupper_q2")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="""
🚧 **Шаг 3/3: Главный барьер.**

Что сейчас является **ГЛАВНЫМ препятствием** 
для быстрого запуска или роста?

💡 *Можете выбрать вариант или написать свой*
            """,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return STARTUPPER_Q3

    async def startupper_q3_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button click for startupper Q3"""
        query = update.callback_query
        await query.answer()
        
        choice = query.data.replace("barrier_", "")
        
        if choice == "custom":
            keyboard = [
                [InlineKeyboardButton("◀️ Назад", callback_data="back_startupper_q2")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text="""
🚧 **Шаг 3/3: Главный барьер.**

Что сейчас является **ГЛАВНЫМ препятствием** 
для быстрого запуска или роста?

💡 *Можете ответить текстом или 🎙️ голосовым сообщением*
                """,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return STARTUPPER_Q3
        else:
            barrier_map = {
                "tech": "Нехватка технических специалистов",
                "mvp": "Нет понимания MVP",
                "design": "Нужен дизайн",
                "marketing": "Нет денег на маркетинг"
            }
            context.user_data['main_barrier'] = barrier_map.get(choice, "Барьер")
            
            # First send inline keyboard with back button
            inline_keyboard = [
                [InlineKeyboardButton("◀️ Назад", callback_data="back_startupper_q3")]
            ]
            inline_markup = InlineKeyboardMarkup(inline_keyboard)
            
            await query.edit_message_text(
                text="""
🤝 Отлично! Готовлю для вас пару мыслей по MVP 
и возможным подводным камням.

Куда отправить и как к вам обращаться?
                """,
                reply_markup=inline_markup,
                parse_mode='Markdown'
            )
            
            # Then send reply keyboard for contact
            contact_keyboard = [
                [KeyboardButton("📲 Поделиться контактом", request_contact=True)],
                [KeyboardButton("✍️ Написать свои контакты")]
            ]
            contact_markup = ReplyKeyboardMarkup(contact_keyboard, resize_keyboard=True, one_time_keyboard=True)
            
            await query.message.reply_text(
                "Выберите удобный способ:",
                reply_markup=contact_markup
            )
            return STARTUPPER_Q4
    
    async def startupper_q3_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save Q3 answer and move to contact"""
        context.user_data['main_barrier'] = self.get_message_text(update, context)
        
        # First send inline keyboard with back button
        inline_keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="back_startupper_q3")]
        ]
        inline_markup = InlineKeyboardMarkup(inline_keyboard)
        
        await update.message.reply_text(
            text="""
🤝 Отлично! Готовлю для вас пару мыслей по MVP 
и возможным подводным камням.

Куда отправить и как к вам обращаться?
            """,
            reply_markup=inline_markup,
            parse_mode='Markdown'
        )
        
        # Then send reply keyboard for contact
        contact_keyboard = [
            [KeyboardButton("📲 Поделиться контактом", request_contact=True)],
            [KeyboardButton("✍️ Написать свои контакты")]
        ]
        contact_markup = ReplyKeyboardMarkup(contact_keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await update.message.reply_text(
            "Выберите удобный способ:",
            reply_markup=contact_markup
        )
        return STARTUPPER_Q4

    async def startupper_q4_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact sharing"""
        user_id = context.user_data['user_id']
        
        # Get contact information
        if update.message.contact:
            phone = update.message.contact.phone_number
            first_name = update.message.contact.first_name
            context.user_data['phone'] = phone
            await update.message.reply_text(
                f"✅ Спасибо, {first_name}! Контакт получен.",
                reply_markup=ReplyKeyboardRemove()
            )
        elif update.message.text and update.message.text == "✍️ Написать свои контакты":
            await update.message.reply_text(
                "📝 Напишите ваши контактные данные (имя, телефон, email):",
                reply_markup=ReplyKeyboardRemove()
            )
            return STARTUPPER_Q4
        elif update.message.text:
            phone = update.message.text
            context.user_data['phone'] = phone
            await update.message.reply_text(
                "✅ Спасибо! Контакт получен.",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            phone = "Not provided"
            context.user_data['phone'] = phone
        
        # Send notification to support group IMMEDIATELY after contact received
        await self.send_new_lead_notification(
            user_id=user_id,
            user_name=update.effective_user.first_name,
            role='startupper',
            context=context
        )
        
        # Save profile
        await self.db.save_startup_profile(
            user_id=user_id,
            problem_solved=context.user_data['problem_solved'],
            current_stage=context.user_data['current_stage'],
            main_barrier=context.user_data['main_barrier'],
            phone=context.user_data.get('phone', 'Not provided')
        )
        
        try:
            loading_msg = await update.message.reply_text("⏳ Анализирую вашу идею и готовлю рекомендации...")
            
            logger.info(f"Generating recommendations for user {user_id}")
            welcome_msg = await self.ai.generate_startup_welcome(
                problem_solved=context.user_data['problem_solved'],
                current_stage=context.user_data['current_stage'],
                main_barrier=context.user_data['main_barrier']
            )
            logger.info(f"Recommendations generated successfully for user {user_id}")
            
            await loading_msg.edit_text("✅ Рекомендации готовы!")
            
            # Send business card
            await self.send_business_card(update.message.chat_id, context)
        except Exception as e:
            logger.error(f"Error generating recommendations for user {user_id}: {e}")
            await update.message.reply_text("❌ Произошла ошибка при генерации рекомендаций. Попробуйте позже.")
            return ROLE_SELECTION
        
        # Send welcome message
        result_text = f"""
✅ <b>Готово! Спасибо за доверие, {update.effective_user.first_name}!</b>

{welcome_msg}

Мы в <b>{self.config.company_name}</b> часто помогаем стартапам с разработкой MVP 
и масштабированием проектов. Будем рады обсудить детали и показать похожие кейсы.

Хорошего дня и удачи в развитии вашей идеи! 🚀
        """
        
        keyboard = [
            [InlineKeyboardButton("🎰 Крутить AI рулетку", web_app=WebAppInfo(url=self.config.webapp_url))]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        logger.info(f"Sending startup solution message to user {user_id}")
        try:
            await update.message.reply_text(result_text, reply_markup=reply_markup, parse_mode='HTML')
            logger.info(f"Startup solution message sent successfully to user {user_id}")
        except Exception as e:
            logger.error(f"Error sending solution message: {e}")
            # Try without formatting if HTML fails
            simple_text = f"✅ Готово! Рекомендации готовы.\n\n{welcome_msg}\n\nСвяжитесь с нами: {self.config.company_website}"
            await update.message.reply_text(simple_text, reply_markup=reply_markup)
        
        return ROLE_SELECTION
    
    # ============= SPECIALIST PATH =============
    async def specialist_q1(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Specialist: Question 1 - Main skill"""
        query = update.callback_query
        
        keyboard = [
            [InlineKeyboardButton("🐍 Python", callback_data="skill_python")],
            [InlineKeyboardButton("⚛️ React/Frontend", callback_data="skill_react")],
            [InlineKeyboardButton("🤖 AI/ML", callback_data="skill_aiml")],
            [InlineKeyboardButton("🎨 UI/UX Design", callback_data="skill_design")],
            [InlineKeyboardButton("☁️ DevOps", callback_data="skill_devops")],
            [InlineKeyboardButton("✍️ Написать свой навык", callback_data="skill_custom")],
            [InlineKeyboardButton("◀️ Назад к выбору роли", callback_data="back_to_roles")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(
                text="""
🔧 **Шаг 1/3: Ключевой навык.**

Какая **ТЕХНОЛОГИЯ** или **НАВЫК** является вашим главным козырем?

💡 *Можете выбрать вариант или 🎙️ назвать свой*
                """,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        return SPECIALIST_Q1

    async def specialist_q1_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button click for specialist Q1"""
        query = update.callback_query
        await query.answer()
        
        choice = query.data.replace("skill_", "")
        
        if choice == "custom":
            await query.edit_message_text(
                text="""
🔧 **Шаг 1/3: Ключевой навык.**

Напишите, какая технология или навык является вашим козырем:

💡 *Можете ответить текстом или 🎙️ голосовым сообщением*
                """,
                parse_mode='Markdown'
            )
            return SPECIALIST_Q1
        else:
            skill_map = {
                "python": "Python",
                "react": "React/Frontend разработка",
                "aiml": "AI/ML",
                "design": "UI/UX Design",
                "devops": "DevOps"
            }
            context.user_data['main_skill'] = skill_map.get(choice, "Специализация")
            
            keyboard = [
                [InlineKeyboardButton("🤖 AI-системы", callback_data="proj_ai")],
                [InlineKeyboardButton("💰 Финтех", callback_data="proj_fintech")],
                [InlineKeyboardButton("🛒 E-commerce", callback_data="proj_ecommerce")],
                [InlineKeyboardButton("📱 Мобильные приложения", callback_data="proj_mobile")],
                [InlineKeyboardButton("🚀 Стартапы", callback_data="proj_startups")],
                [InlineKeyboardButton("✍️ Написать свой вариант", callback_data="proj_custom")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_specialist_q1")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text="""
🎯 **Шаг 2/3: Идеальный проект.**

В каких **ПРОЕКТАХ** вы хотели бы участвовать? Что вас зажигает?

💡 *Можете выбрать вариант или написать свой*
                """,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return SPECIALIST_Q2
    
    async def specialist_q1_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save Q1 answer and move to Q2"""
        context.user_data['main_skill'] = self.get_message_text(update, context)
        
        await update.message.reply_text(
            text="""
🎯 **Шаг 2/3: Идеальный проект.**

В каких **ПРОЕКТАХ** вы хотели бы участвовать? Что вас зажигает?

_(Примеры: сложные AI-системы, финтех, e-commerce, 
мобильные приложения, стартапы)_
            """,
            parse_mode='Markdown'
        )
        return SPECIALIST_Q2

    async def specialist_q2_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button click for specialist Q2"""
        query = update.callback_query
        await query.answer()
        
        choice = query.data.replace("proj_", "")
        
        if choice == "custom":
            await query.edit_message_text(
                text="""
🎯 **Шаг 2/3: Идеальный проект.**

Напишите, в каких проектах вы хотели бы участвовать:

💡 *Можете ответить текстом или 🎙️ голосовым сообщением*
                """,
                parse_mode='Markdown'
            )
            return SPECIALIST_Q2
        else:
            proj_map = {
                "ai": "Сложные AI-системы",
                "fintech": "Финтех",
                "ecommerce": "E-commerce",
                "mobile": "Мобильные приложения",
                "startups": "Стартапы"
            }
            context.user_data['project_interests'] = proj_map.get(choice, "Проекты")
            
            keyboard = [
                [InlineKeyboardButton("Проектная работа", callback_data="format_project")],
                [InlineKeyboardButton("Частичная занятость", callback_data="format_part_time")],
                [InlineKeyboardButton("Полная занятость", callback_data="format_full_time")],
                [InlineKeyboardButton("◀️ Назад", callback_data="back_specialist_q2")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text="""
💼 **Шаг 3/3: Формат работы.**

Какой **ФОРМАТ** сотрудничества вам интересен?
                """,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return SPECIALIST_Q3
    
    async def specialist_q2_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save Q2 answer and move to Q3"""
        context.user_data['project_interests'] = self.get_message_text(update, context)
        
        keyboard = [
            [InlineKeyboardButton("Проектная работа", callback_data="format_project")],
            [InlineKeyboardButton("Частичная занятость", callback_data="format_part_time")],
            [InlineKeyboardButton("Полная занятость", callback_data="format_full_time")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_specialist_q2")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            text="""
💼 **Шаг 3/3: Формат работы.**

Какой **ФОРМАТ** сотрудничества вам интересен?
            """,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return SPECIALIST_Q3

    async def specialist_q3_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save Q3 answer and move to contact"""
        query = update.callback_query
        await query.answer()
        
        work_format = query.data.replace("format_", "")
        context.user_data['work_format'] = work_format
        
        await query.edit_message_text(
            text=f"""
🤝 Спасибо! У нас в **{self.config.company_name}** часто появляются проекты, 
где нужны именно такие специалисты.

Оставьте контакт, чтобы мы могли с вами связаться.
            """,
            parse_mode='Markdown'
        )
        
        # Send reply keyboard for contact
        contact_keyboard = [
            [KeyboardButton("📲 Поделиться контактом", request_contact=True)],
            [KeyboardButton("✍️ Написать свои контакты")]
        ]
        contact_markup = ReplyKeyboardMarkup(contact_keyboard, resize_keyboard=True, one_time_keyboard=True)
        
        await query.message.reply_text(
            "Выберите удобный способ:",
            reply_markup=contact_markup
        )
        return SPECIALIST_Q4

    async def specialist_q4_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact sharing"""
        user_id = context.user_data['user_id']
        
        # Get contact information
        if update.message.contact:
            phone = update.message.contact.phone_number
            first_name = update.message.contact.first_name
            context.user_data['phone'] = phone
            await update.message.reply_text(
                f"✅ Спасибо, {first_name}! Контакт получен.",
                reply_markup=ReplyKeyboardRemove()
            )
        elif update.message.text and update.message.text == "✍️ Написать свои контакты":
            await update.message.reply_text(
                "📝 Напишите ваши контактные данные (имя, телефон, email):",
                reply_markup=ReplyKeyboardRemove()
            )
            return SPECIALIST_Q4
        elif update.message.text:
            phone = update.message.text
            context.user_data['phone'] = phone
            await update.message.reply_text(
                "✅ Спасибо! Контакт получен.",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            phone = "Not provided"
            context.user_data['phone'] = phone
        
        # Send notification to support group IMMEDIATELY after contact received
        await self.send_new_lead_notification(
            user_id=user_id,
            user_name=update.effective_user.first_name,
            role='specialist',
            context=context
        )
        
        # Save profile
        await self.db.save_specialist_profile(
            user_id=user_id,
            main_skill=context.user_data['main_skill'],
            project_interests=context.user_data['project_interests'],
            work_format=context.user_data['work_format'],
            phone=context.user_data.get('phone', 'Not provided')
        )
        
        loading_msg = await update.message.reply_text("⏳ Добавляю вас в нашу базу талантов...")
        
        welcome_msg = await self.ai.generate_specialist_welcome(
            main_skill=context.user_data['main_skill'],
            project_interests=context.user_data['project_interests'],
            work_format=context.user_data['work_format']
        )
        
        await loading_msg.edit_text("✅ Вы добавлены в базу!")
        
        # Send business card
        await self.send_business_card(update.message.chat_id, context)
        
        # Send welcome message
        result_text = f"""
✅ **Отлично! Вы успешно добавлены в нашу базу специалистов.**

{welcome_msg}

Спасибо за интерес к **{self.config.company_name}**! 🚀
        """
        
        keyboard = [
            [InlineKeyboardButton("🎰 Крутить AI рулетку", web_app=WebAppInfo(url=self.config.webapp_url))]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(result_text, reply_markup=reply_markup, parse_mode='Markdown')
        
        return ROLE_SELECTION
    
    # ============= RESEARCHER PATH =============
    async def researcher_path(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Researcher: Quick company overview"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        context.user_data['user_id'] = user.id
        context.user_data['role'] = 'researcher'
        
        # Send business card first
        await self.send_business_card(query.message.chat_id, context)
        
        welcome_text = f"""
🌟 Рад, что вы заглянули!

Мы в **{self.config.company_name}** создаем интеллектуальные IT-решения для бизнеса.
От автоматизации рутины до сложных AI-систем.

Что бы вы хотели узнать о нас в первую очередь?
        """
        
        keyboard = [
            [InlineKeyboardButton("🚀 Наши лучшие кейсы", callback_data="info_cases")],
            [InlineKeyboardButton("🤖 Технологический стек", callback_data="info_tech")],
            [InlineKeyboardButton("🤝 Связаться с нами", callback_data="info_contact")],
            [InlineKeyboardButton("◀️ Назад к выбору роли", callback_data="back_to_roles")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        return RESEARCHER

    async def researcher_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle researcher info requests"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        user_id = context.user_data.get('user_id', user.id)
        info_type = query.data.replace("info_", "")
        
        # Store what user was interested in
        context.user_data['interest'] = info_type
        
        if info_type == "cases":
            text = """
🚀 **Наши лучшие кейсы:**

1️⃣ **E-commerce Automation** - Сэкономили 30 часов в неделю для компании с 50 сотрудниками
2️⃣ **AI Customer Support** - Внедрили чатбот, обрабатывающий 80% вопросов автоматически
3️⃣ **Data Pipeline** - Создали систему обработки данных для финтех-стартапа

Хотите узнать больше? Посетите наш сайт или свяжитесь с нами!
            """
        elif info_type == "tech":
            text = """
🤖 **Наш технологический стек:**

🐍 **Backend:** Python, FastAPI, Django
⚛️ **Frontend:** React, TypeScript, TailwindCSS
🗄️ **Database:** PostgreSQL, Redis
🤖 **AI/ML:** OpenAI, OpenRouter, LangChain
☁️ **Cloud:** Docker, Kubernetes, AWS

Заинтересовались? Давайте обсудим ваш проект!
            """
        else:  # contact
            contact_parts = ["🤝 **Свяжитесь с нами:**"]
            
            if self.config.company_email:
                contact_parts.append(f"\n📧 Email: {self.config.company_email}")
            
            if self.config.company_phone:
                contact_parts.append(f"\n📞 Телефон: {self.config.company_phone}")
            
            if self.config.company_telegram:
                contact_parts.append(f"\n📱 Telegram: {self.config.company_telegram}")
            
            if self.config.company_website:
                contact_parts.append(f"\n🌐 Website: {self.config.company_website}")
            
            contact_parts.append("\n\nБудем рады обсудить ваш проект!")
            
            text = "\n".join(contact_parts)
        
        # Send business card
        await self.send_business_card(query.message.chat_id, context)
        
        # Final message with buttons
        final_text = f"""
{text}

---

Спасибо за интерес к **{self.config.company_name}**! 🚀
        """
        
        # Build keyboard based on info type
        keyboard = []
        
        if info_type == "cases":
            keyboard.append([InlineKeyboardButton("🌐 Посмотреть все кейсы", url=self.config.cases_link)])
        
        keyboard.extend([
            [InlineKeyboardButton("💰 Расчет стоимости проекта", callback_data="request_cost_calculation")],
            [InlineKeyboardButton("🌐 Посетить наш сайт", url=self.config.company_website)],
            [InlineKeyboardButton("🗓 Запланировать звонок", url=self.config.book_call_link)],
            [InlineKeyboardButton("💬 Связаться с сотрудником", callback_data="contact_support")],
            [InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_roles")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(final_text, reply_markup=reply_markup, parse_mode='Markdown')
        
        # Send notification to support group about new lead
        await self.send_new_lead_notification(
            user_id=user_id,
            user_name=user.first_name,
            role='researcher',
            context=context
        )
        
        return ROLE_SELECTION

    async def send_business_card(self, chat_id, context: ContextTypes.DEFAULT_TYPE):
        """Send business card image"""
        try:
            # Build caption with checks for empty values
            caption_parts = [f"🌟 **{self.config.company_name}**"]
            
            if self.config.company_description:
                caption_parts.append(f"\n{self.config.company_description}")
            
            if self.config.company_email:
                caption_parts.append(f"\n📧 {self.config.company_email}")
            
            if self.config.company_phone:
                caption_parts.append(f"\n📞 {self.config.company_phone}")
            
            if self.config.company_telegram:
                caption_parts.append(f"\n📱 {self.config.company_telegram}")
            
            if self.config.company_website:
                caption_parts.append(f"\n🌐 {self.config.company_website}")
            
            caption = "\n".join(caption_parts)
            
            with open('/app/assets/business_card_banner.png', 'rb') as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Failed to send business card: {e}")

    async def handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Universal handler for voice messages
        Downloads, transcribes and processes voice messages
        """
        user_id = update.effective_user.id
        logger.info(f"Received voice message from user {user_id}")
        
        try:
            # Show typing indicator
            await update.message.chat.send_action(ChatAction.TYPING)
            
            # Send processing message with more details
            processing_msg = await update.message.reply_text(
                "🎙️ *Получил голосовое сообщение!*\n\n"
                "⏳ Пожалуйста, подождите...\n"
                "Сейчас распознаю вашу речь через AI.",
                parse_mode='Markdown'
            )
            logger.info(f"Processing message sent to user {user_id}")
            
            # Get voice file
            voice = update.message.voice
            file = await context.bot.get_file(voice.file_id)
            logger.info(f"Voice file info received: file_id={voice.file_id}, duration={voice.duration}s")
            
            # Create temporary file for audio
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as temp_audio:
                temp_audio_path = temp_audio.name
            
            # Download audio file
            logger.info(f"Downloading voice file to {temp_audio_path}...")
            await file.download_to_drive(temp_audio_path)
            logger.info(f"Voice message downloaded successfully: {temp_audio_path}")
            
            # Update processing message
            await processing_msg.edit_text(
                "🎙️ *Получил голосовое сообщение!*\n\n"
                "✅ Файл загружен\n"
                "🤖 Распознаю речь через AI...",
                parse_mode='Markdown'
            )
            
            # Transcribe audio
            logger.info(f"Starting transcription for user {user_id}...")
            transcription = await self.ai.transcribe_audio(temp_audio_path)
            logger.info(f"Transcription completed: {transcription[:100]}...")
            
            # Clean up temporary file
            try:
                os.unlink(temp_audio_path)
                logger.info(f"Temporary file deleted: {temp_audio_path}")
            except Exception as e:
                logger.warning(f"Failed to delete temp file: {e}")
            
            # Check if transcription was successful
            if transcription.startswith("Извините") or transcription.startswith("Ошибка"):
                logger.error(f"Transcription failed: {transcription}")
                await processing_msg.delete()
                await update.message.reply_text(
                    f"❌ {transcription}\n\nПожалуйста, попробуйте написать текстом."
                )
                return None
            
            # Delete processing message
            await processing_msg.delete()
            
            # Store transcription in context for text handlers to use
            context.user_data['voice_transcription'] = transcription
            
            # Show transcription to user with confirmation
            logger.info(f"Showing transcription to user {user_id}")
            
            # Determine which "Back" button to show based on current state
            back_button_data = "back_to_roles"  # default
            
            # Check conversation state to provide appropriate back button
            if 'role' in context.user_data:
                role = context.user_data['role']
                if role == 'entrepreneur':
                    if 'process_pain' not in context.user_data:
                        back_button_data = "back_to_roles"
                    elif 'department_affected' not in context.user_data:
                        back_button_data = "back_entrepreneur_q1"
                elif role == 'startupper':
                    if 'problem_solved' not in context.user_data:
                        back_button_data = "back_to_roles"
                    elif 'main_barrier' not in context.user_data:
                        back_button_data = "back_startupper_q1"
                elif role == 'specialist':
                    if 'main_skill' not in context.user_data:
                        back_button_data = "back_to_roles"
                    elif 'project_interests' not in context.user_data:
                        back_button_data = "back_specialist_q1"
            
            keyboard = [
                [InlineKeyboardButton("💬 Связаться с сотрудником", callback_data="contact_support")],
                [InlineKeyboardButton("◀️ Назад", callback_data=back_button_data)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ *Распознано:* \"{transcription}\"\n\n"
                f"⏳ Обрабатываю ваш ответ...",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            logger.info(f"Voice message processing completed successfully for user {user_id}")
            # Return transcription so it can be processed by the handler
            return transcription
            
        except Exception as e:
            logger.error(f"Error handling voice message from user {user_id}: {e}", exc_info=True)
            try:
                await update.message.reply_text(
                    "❌ Произошла ошибка при обработке голосового сообщения.\n\n"
                    "Пожалуйста, попробуйте написать текстом."
                )
            except Exception as send_error:
                logger.error(f"Failed to send error message: {send_error}")
            return None

    async def back_to_roles(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to role selection"""
        query = update.callback_query
        await query.answer()
        
        welcome_text = f"""
🤖 **Привет! Я — AI-бот от {self.config.company_name}**

Я анализирую вашу проблему и **предложу конкретное решение** за 2 минуты.

🎯 Отвечу на 3-4 вопроса
🧠 Проанализирую вашу ситуацию
✨ Подготовлю персональные рекомендации

**🎰 Бонус:** В конце вас ждёт сюрприз — рулетка с реальным денежным призом до **30 000 ₽** на услуги нашей компании!

Выберите, что вам ближе:
        """
        
        keyboard = [
            [InlineKeyboardButton("🚀 У меня есть бизнес", callback_data="role_entrepreneur")],
            [InlineKeyboardButton("💡 У меня есть идея/стартап", callback_data="role_startupper")],
            [InlineKeyboardButton("💻 Я разработчик/специалист", callback_data="role_specialist")],
            [InlineKeyboardButton("📈 Ищу интересный проект", callback_data="role_researcher")],
            [InlineKeyboardButton("💬 Связаться с сотрудником", callback_data="contact_support")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        return ROLE_SELECTION
    
    async def back_entrepreneur_q1(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to entrepreneur Q1"""
        query = update.callback_query
        await query.answer()
        return await self.entrepreneur_q1(update, context)
    
    async def back_entrepreneur_q2(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to entrepreneur Q2"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("До 10 часов", callback_data="time_0-10")],
            [InlineKeyboardButton("10-30 часов", callback_data="time_10-30")],
            [InlineKeyboardButton("Больше 30 часов", callback_data="time_30+")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_entrepreneur_q1")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="""
⏱️ **Шаг 2/4: Масштаб проблемы.**

Как бы вы оценили, сколько **рабочих часов в неделю** 
вся команда тратит на этот процесс?
            """,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return ENTREPRENEUR_Q2
    
    async def back_entrepreneur_q3(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to entrepreneur Q3"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("💼 Отдел продаж", callback_data="dept_sales")],
            [InlineKeyboardButton("📞 Поддержка клиентов", callback_data="dept_support")],
            [InlineKeyboardButton("💰 Бухгалтерия", callback_data="dept_accounting")],
            [InlineKeyboardButton("🚚 Логистика", callback_data="dept_logistics")],
            [InlineKeyboardButton("✍️ Написать свой вариант", callback_data="dept_custom")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_entrepreneur_q2")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="""
🏢 **Шаг 3/4: Эпицентр рутины.**

Какой **отдел** или какая **роль** в компании больше всего страдает 
от этой задачи?

💡 *Можете выбрать вариант или написать свой*
            """,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return ENTREPRENEUR_Q3

    async def back_specialist_q1(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to specialist Q1"""
        query = update.callback_query
        await query.answer()
        return await self.specialist_q1(update, context)
    
    async def back_specialist_q2(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to specialist Q2"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("🤖 AI-системы", callback_data="proj_ai")],
            [InlineKeyboardButton("💰 Финтех", callback_data="proj_fintech")],
            [InlineKeyboardButton("🛒 E-commerce", callback_data="proj_ecommerce")],
            [InlineKeyboardButton("📱 Мобильные приложения", callback_data="proj_mobile")],
            [InlineKeyboardButton("🚀 Стартапы", callback_data="proj_startups")],
            [InlineKeyboardButton("✍️ Написать свой вариант", callback_data="proj_custom")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_specialist_q1")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="""
🎯 **Шаг 2/3: Идеальный проект.**

В каких **ПРОЕКТАХ** вы хотели бы участвовать? Что вас зажигает?

💡 *Можете выбрать вариант или написать свой*
            """,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return SPECIALIST_Q2
    
    async def back_startupper_q1(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to startupper Q1"""
        query = update.callback_query
        await query.answer()
        return await self.startupper_q1(update, context)
    
    async def back_startupper_q2(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to startupper Q2"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("Только идея", callback_data="stage_idea")],
            [InlineKeyboardButton("Есть прототип", callback_data="stage_prototype")],
            [InlineKeyboardButton("Первые клиенты", callback_data="stage_clients")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_startupper_q1")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="""
🎯 **Шаг 2/3: Текущий этап.**

На каком вы сейчас этапе?
            """,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return STARTUPPER_Q2
    
    async def back_startupper_q3(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to startupper Q3"""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("👨‍💻 Нехватка разработчиков", callback_data="barrier_tech")],
            [InlineKeyboardButton("🎯 Нет понимания MVP", callback_data="barrier_mvp")],
            [InlineKeyboardButton("🎨 Нужен дизайн", callback_data="barrier_design")],
            [InlineKeyboardButton("💰 Нет денег на маркетинг", callback_data="barrier_marketing")],
            [InlineKeyboardButton("✍️ Написать свой вариант", callback_data="barrier_custom")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_startupper_q2")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="""
🚧 **Шаг 3/3: Главный барьер.**

Что сейчас является **ГЛАВНЫМ препятствием** 
для быстрого запуска или роста?

💡 *Можете выбрать вариант или написать свой*
            """,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return STARTUPPER_Q3

    
    async def send_new_lead_notification(self, user_id: int, user_name: str, role: str, context: ContextTypes.DEFAULT_TYPE):
        """Send notification to support group about new lead"""
        try:
            # Get full user information from database
            db_user_info = await self.db.get_user_full_info(user_id)
            
            role_map = {
                'entrepreneur': '🚀 Предприниматель',
                'startupper': '💡 Стартапер',
                'specialist': '💻 Специалист',
                'researcher': '📈 Исследователь'
            }
            
            notification_text = f"""
🎉 **НОВАЯ ЗАЯВКА!**

👤 **Пользователь:**
├ ID: `{user_id}`
├ Имя: {user_name}
├ Username: @{db_user_info.get('username', 'не указан') if db_user_info else 'не указан'}
└ Роль: {role_map.get(role, 'Не указана')}

📋 **Данные анкеты:**
{self._format_user_survey_data(context.user_data, role)}

📞 **Контакты:**
├ Телефон: {db_user_info.get('phone_number', 'Не указан') if db_user_info else 'Не указан'}
├ Email: {db_user_info.get('email', 'Не указан') if db_user_info else 'Не указан'}
├ Компания: {db_user_info.get('company', 'Не указана') if db_user_info else 'Не указана'}
└ Должность: {db_user_info.get('position', 'Не указана') if db_user_info else 'Не указана'}

🔗 **Ссылка:** [Открыть диалог](tg://user?id={user_id})
            """
            
            await context.bot.send_message(
                chat_id=self.config.support_group_id,
                text=notification_text,
                parse_mode='Markdown'
            )
            
            logger.info(f"New lead notification sent for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send new lead notification: {e}", exc_info=True)
    
    def _format_user_survey_data(self, user_data: dict, role: str) -> str:
        """Format user survey data for notification"""
        if role == 'entrepreneur':
            return f"""├ Проблема: {user_data.get('process_pain', 'Не указано')}
├ Потери времени: {user_data.get('time_lost', 'Не указано')}
└ Отдел: {user_data.get('department_affected', 'Не указано')}"""
        elif role == 'startupper':
            return f"""├ Проблема: {user_data.get('problem_solved', 'Не указано')}
├ Стадия: {user_data.get('current_stage', 'Не указано')}
└ Барьер: {user_data.get('main_barrier', 'Не указано')}"""
        elif role == 'specialist':
            return f"""├ Навык: {user_data.get('main_skill', 'Не указано')}
├ Проекты: {user_data.get('project_type', 'Не указано')}
└ Интерес: {user_data.get('interest', 'Не указано')}"""
        elif role == 'researcher':
            interest_map = {
                'cases': 'Кейсы',
                'tech': 'Технологический стек',
                'contact': 'Контактная информация'
            }
            interest = interest_map.get(user_data.get('interest', ''), 'Не указано')
            return f"""└ Интересовался: {interest}"""
        return "Нет данных"
    
    async def handle_cost_calculation_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle cost calculation request"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        user_id = user.id
        
        try:
            # Get full user information
            db_user_info = await self.db.get_user_full_info(user_id)
            
            role = context.user_data.get('role', 'unknown')
            role_map = {
                'entrepreneur': '🚀 Предприниматель',
                'startupper': '💡 Стартапер',
                'specialist': '💻 Специалист',
                'researcher': '📈 Исследователь'
            }
            
            # Send notification to support group
            calculation_request = f"""
💰 **ЗАПРОС РАСЧЕТА СТОИМОСТИ**

👤 **Пользователь:**
├ ID: `{user_id}`
├ Имя: {user.first_name} {user.last_name or ''}
├ Username: @{user.username if user.username else 'не указан'}
└ Роль: {role_map.get(role, 'Не указана')}

📋 **Данные анкеты:**
{self._format_user_survey_data(context.user_data, role)}

📞 **Контакты:**
├ Телефон: {db_user_info.get('phone_number', 'Не указан') if db_user_info else 'Не указан'}
├ Email: {db_user_info.get('email', 'Не указан') if db_user_info else 'Не указан'}
├ Компания: {db_user_info.get('company', 'Не указана') if db_user_info else 'Не указана'}
├ Должность: {db_user_info.get('position', 'Не указана') if db_user_info else 'Не указана'}
└ Сайт: {db_user_info.get('website', 'Не указан') if db_user_info else 'Не указан'}

🔗 **Ссылка:** [Открыть диалог](tg://user?id={user_id})

⚠️ **Пользователь ждет расчет стоимости проекта!**
            """
            
            await context.bot.send_message(
                chat_id=self.config.support_group_id,
                text=calculation_request,
                parse_mode='Markdown'
            )
            
            # Confirm to user
            await query.edit_message_reply_markup(reply_markup=None)
            await update.effective_message.reply_text(
                text="""
✅ **Запрос отправлен!**

Наш менеджер получил ваш запрос на расчет стоимости проекта и свяжется с вами в ближайшее время для уточнения деталей.

Обычно мы готовим предварительную оценку в течение 1-2 рабочих дней.

Спасибо за интерес! 🙏
                """,
                parse_mode='Markdown'
            )
            
            logger.info(f"Cost calculation request sent for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error handling cost calculation request: {e}", exc_info=True)
            await query.edit_message_text(
                text="⚠️ Произошла ошибка. Попробуйте связаться с нами через кнопку 'Связаться с сотрудником'."
            )
        
        return ROLE_SELECTION
    
    async def contact_support(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle contact support request"""
        query = update.callback_query
        await query.answer()
        
        # Ask user to describe their question
        await query.edit_message_text(
            text="""
💬 **Связь с сотрудником**

Опишите ваш вопрос или проблему, и наш специалист свяжется с вами в ближайшее время.

Напишите ваше сообщение текстом или отправьте голосовое сообщение 🎙️
            """,
            parse_mode='Markdown'
        )
        return CONTACT_SUPPORT
    
    async def handle_support_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user's support message and send to support group"""
        user = update.effective_user
        user_message = self.get_message_text(update, context)
        
        try:
            # Get full user information from database
            db_user_info = await self.db.get_user_full_info(user.id)
            
            # Collect user information
            user_info = {
                'id': user.id,
                'first_name': user.first_name or 'Не указано',
                'last_name': user.last_name or '',
                'username': f"@{user.username}" if user.username else 'Не указан',
                'phone': 'Не указан',
                'email': 'Не указан',
                'language': user.language_code or 'unknown',
                'is_premium': '✅' if user.is_premium else '❌',
                'company': 'Не указана',
                'position': 'Не указана',
                'website': 'Не указан'
            }
            
            # Update with database info if available
            if db_user_info:
                if db_user_info.get('phone_number'):
                    user_info['phone'] = db_user_info['phone_number']
                if db_user_info.get('email'):
                    user_info['email'] = db_user_info['email']
                if db_user_info.get('company'):
                    user_info['company'] = db_user_info['company']
                if db_user_info.get('position'):
                    user_info['position'] = db_user_info['position']
                if db_user_info.get('website'):
                    user_info['website'] = db_user_info['website']
            
            # Get user's role from context or database
            role_map = {
                'entrepreneur': '🚀 Предприниматель',
                'startupper': '💡 Стартапер',
                'specialist': '💻 Специалист',
                'researcher': '📈 Исследователь'
            }
            user_role = role_map.get(context.user_data.get('role', ''), 'Не указана')
            if db_user_info and db_user_info.get('role'):
                user_role = role_map.get(db_user_info['role'], user_role)
            
            # Format message for support group
            support_message = f"""
🆘 **НОВОЕ ОБРАЩЕНИЕ В ПОДДЕРЖКУ**

👤 **Информация о пользователе:**
├ ID: `{user_info['id']}`
├ Имя: {user_info['first_name']} {user_info['last_name']}
├ Username: {user_info['username']}
├ Телефон: {user_info['phone']}
├ Email: {user_info['email']}
├ Компания: {user_info['company']}
├ Должность: {user_info['position']}
├ Сайт: {user_info['website']}
├ Язык: {user_info['language']}
├ Premium: {user_info['is_premium']}
└ Роль: {user_role}
"""
            
            # Add profile data if available
            if db_user_info and db_user_info.get('profile_data'):
                profile_data = db_user_info['profile_data']
                
                if db_user_info.get('role') == 'entrepreneur':
                    support_message += f"""
📊 **Ответы предпринимателя:**
├ Процесс боли: {profile_data.get('process_pain', 'Не указано')}
├ Потери времени: {profile_data.get('time_lost', 'Не указано')}
└ Затронутый отдел: {profile_data.get('department_affected', 'Не указано')}
"""
                
                elif db_user_info.get('role') == 'startupper':
                    support_message += f"""
💡 **Ответы стартапера:**
├ Решаемая проблема: {profile_data.get('problem_solved', 'Не указано')}
├ Текущая стадия: {profile_data.get('current_stage', 'Не указано')}
└ Основной барьер: {profile_data.get('main_barrier', 'Не указано')}
"""
                
                elif db_user_info.get('role') == 'specialist':
                    support_message += f"""
💻 **Ответы специалиста:**
├ Основной навык: {profile_data.get('main_skill', 'Не указано')}
├ Интересы проекта: {profile_data.get('project_interests', 'Не указано')}
└ Формат работы: {profile_data.get('work_format', 'Не указано')}
"""
            
            support_message += f"""
💬 **Сообщение от пользователя:**
{user_message}

🔗 **Ссылка на пользователя:** [Открыть диалог](tg://user?id={user_info['id']})

⏰ Время обращения: {update.message.date.strftime('%Y-%m-%d %H:%M:%S')}
            """
            
            # Send to support group
            await context.bot.send_message(
                chat_id=self.config.support_group_id,
                text=support_message,
                parse_mode='Markdown'
            )
            
            # If user has business card data, send it as well
            if db_user_info and db_user_info.get('business_card_data'):
                card_data = db_user_info['business_card_data']
                card_text = "📇 **Данные визитки пользователя:**\n\n"
                
                if isinstance(card_data, dict):
                    for key, value in card_data.items():
                        if value:
                            card_text += f"• **{key.capitalize()}:** {value}\n"
                    
                    await context.bot.send_message(
                        chat_id=self.config.support_group_id,
                        text=card_text,
                        parse_mode='Markdown'
                    )
            
            logger.info(f"Support request sent to group from user {user.id}")
            
            # Confirm to user with main menu button
            confirmation_text = """
✅ **Ваше сообщение отправлено!**

Наш специалист получил ваше обращение и свяжется с вами в ближайшее время.

Обычно мы отвечаем в течение 1-2 часов в рабочее время (пн-пт, 10:00-19:00 МСК).

Спасибо за обращение! 🙏
            """
            
            keyboard = [
                [InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_roles")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                text=confirmation_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            return ROLE_SELECTION
            
        except Exception as e:
            logger.error(f"Error sending support message: {e}", exc_info=True)
            
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="contact_support")],
                [InlineKeyboardButton("🏠 Вернуться к началу", callback_data="back_to_roles")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"❌ Произошла ошибка при отправке сообщения.\n\n"
                f"Пожалуйста, попробуйте позже или напишите нам напрямую:\n"
                f"📧 {self.config.company_email}",
                reply_markup=reply_markup
            )
            return ROLE_SELECTION
    
    async def handle_roulette_result(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle roulette result from mini app"""
        user = update.effective_user
        web_app_data = update.message.web_app_data.data
        
        try:
            import json
            data = json.loads(web_app_data)
            prize = data.get('prize', 0)
            
            logger.info(f"User {user.id} won {prize} RUB in roulette")
            
            # Send congratulations message with buttons
            congrats_text = f"""
🎉 **Поздравляем, {user.first_name}!**

Вы выиграли **{prize:,} ₽** на услуги нашей компании!

Этот приз можно использовать как скидку при заказе разработки проекта.

Хотите узнать стоимость вашего проекта с учетом скидки?
            """
            
            keyboard = [
                [InlineKeyboardButton("💰 Расчет стоимости проекта", callback_data="request_cost_calculation")],
                [InlineKeyboardButton("🏠 В главное меню", callback_data="back_to_roles")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                text=congrats_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error handling roulette result: {e}")
    
    async def roulette_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /roulette command - open mini app"""
        user = update.effective_user
        logger.info(f"User {user.id} ({user.first_name}) requested roulette")
        
        # Create keyboard with Web App button that opens mini app
        keyboard = [
            [InlineKeyboardButton(
                "🎰 Крутить рулетку призов", 
                web_app=WebAppInfo(url=self.config.webapp_url)
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🎰 **Рулетка призов**\n\n"
            "Нажмите кнопку ниже, чтобы открыть рулетку и попытать удачу!\n\n"
            "💰 **Призы:**\n"
            "• 5 000 ₽\n"
            "• 10 000 ₽\n"
            "• 15 000 ₽\n"
            "• 20 000 ₽\n"
            "• 25 000 ₽\n"
            "• 30 000 ₽\n\n"
            "🎁 Вы можете выиграть скидку на услуги нашей компании!",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel conversation"""
        await update.message.reply_text("Диалог отменен. Спасибо за внимание! 👋")
        return ConversationHandler.END

def main():
    """Start the bot"""
    bot = NeuroConnectorBot()
    
    # Create application
    application = Application.builder().token(bot.config.telegram_token).build()
    
    # Create wrapper for voice message handling
    async def handle_voice_and_text_entrepreneur_q1(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.voice:
            logger.info("WRAPPER: Voice message detected in entrepreneur_q1")
            transcription = await bot.handle_voice_message(update, context)
            if transcription:
                return await bot.entrepreneur_q1_answer(update, context)
        else:
            return await bot.entrepreneur_q1_answer(update, context)
    
    async def handle_voice_and_text_entrepreneur_q3(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.voice:
            logger.info("WRAPPER: Voice message detected in entrepreneur_q3")
            transcription = await bot.handle_voice_message(update, context)
            if transcription:
                return await bot.entrepreneur_q3_answer(update, context)
        else:
            return await bot.entrepreneur_q3_answer(update, context)
    
    async def handle_voice_and_text_startupper_q1(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.voice:
            logger.info("WRAPPER: Voice message detected in startupper_q1")
            transcription = await bot.handle_voice_message(update, context)
            if transcription:
                return await bot.startupper_q1_answer(update, context)
        else:
            return await bot.startupper_q1_answer(update, context)
    
    async def handle_voice_and_text_startupper_q3(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.voice:
            logger.info("WRAPPER: Voice message detected in startupper_q3")
            transcription = await bot.handle_voice_message(update, context)
            if transcription:
                return await bot.startupper_q3_answer(update, context)
        else:
            return await bot.startupper_q3_answer(update, context)
    
    async def handle_voice_and_text_specialist_q1(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.voice:
            logger.info("WRAPPER: Voice message detected in specialist_q1")
            transcription = await bot.handle_voice_message(update, context)
            if transcription:
                return await bot.specialist_q1_answer(update, context)
        else:
            return await bot.specialist_q1_answer(update, context)
    
    async def handle_voice_and_text_specialist_q2(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.voice:
            logger.info("WRAPPER: Voice message detected in specialist_q2")
            transcription = await bot.handle_voice_message(update, context)
            if transcription:
                return await bot.specialist_q2_answer(update, context)
        else:
            return await bot.specialist_q2_answer(update, context)
    
    async def handle_voice_and_text_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.voice:
            logger.info("WRAPPER: Voice message detected in support")
            transcription = await bot.handle_voice_message(update, context)
            if transcription:
                return await bot.handle_support_message(update, context)
        else:
            return await bot.handle_support_message(update, context)
    
    # Create conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", bot.start)],
        allow_reentry=True,
        states={
            ROLE_SELECTION: [
                CallbackQueryHandler(bot.back_to_roles, pattern="^back_to_roles$"),
                CallbackQueryHandler(bot.contact_support, pattern="^contact_support$"),
                CallbackQueryHandler(bot.handle_cost_calculation_request, pattern="^request_cost_calculation$"),
                CallbackQueryHandler(bot.role_selection)
            ],
            ENTREPRENEUR_Q1: [
                CallbackQueryHandler(bot.back_to_roles, pattern="^back_to_roles$"),
                CallbackQueryHandler(bot.entrepreneur_q1_button, pattern="^pain_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voice_and_text_entrepreneur_q1),
                MessageHandler(filters.VOICE, handle_voice_and_text_entrepreneur_q1)
            ],
            ENTREPRENEUR_Q2: [
                CallbackQueryHandler(bot.back_entrepreneur_q1, pattern="^back_entrepreneur_q1$"),
                CallbackQueryHandler(bot.entrepreneur_q2_answer)
            ],
            ENTREPRENEUR_Q3: [
                CallbackQueryHandler(bot.back_entrepreneur_q2, pattern="^back_entrepreneur_q2$"),
                CallbackQueryHandler(bot.entrepreneur_q3_button, pattern="^dept_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voice_and_text_entrepreneur_q3),
                MessageHandler(filters.VOICE, handle_voice_and_text_entrepreneur_q3)
            ],
            ENTREPRENEUR_Q4: [
                CallbackQueryHandler(bot.back_entrepreneur_q3, pattern="^back_entrepreneur_q3$"),
                MessageHandler(filters.CONTACT, bot.entrepreneur_q4_answer),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.entrepreneur_q4_answer)
            ],
            STARTUPPER_Q1: [
                CallbackQueryHandler(bot.back_to_roles, pattern="^back_to_roles$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voice_and_text_startupper_q1),
                MessageHandler(filters.VOICE, handle_voice_and_text_startupper_q1)
            ],
            STARTUPPER_Q2: [
                CallbackQueryHandler(bot.back_startupper_q1, pattern="^back_startupper_q1$"),
                CallbackQueryHandler(bot.startupper_q2_answer)
            ],
            STARTUPPER_Q3: [
                CallbackQueryHandler(bot.back_startupper_q2, pattern="^back_startupper_q2$"),
                CallbackQueryHandler(bot.startupper_q3_button, pattern="^barrier_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voice_and_text_startupper_q3),
                MessageHandler(filters.VOICE, handle_voice_and_text_startupper_q3)
            ],
            STARTUPPER_Q4: [
                CallbackQueryHandler(bot.back_startupper_q3, pattern="^back_startupper_q3$"),
                MessageHandler(filters.CONTACT, bot.startupper_q4_answer),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.startupper_q4_answer)
            ],
            SPECIALIST_Q1: [
                CallbackQueryHandler(bot.back_to_roles, pattern="^back_to_roles$"),
                CallbackQueryHandler(bot.specialist_q1_button, pattern="^skill_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voice_and_text_specialist_q1),
                MessageHandler(filters.VOICE, handle_voice_and_text_specialist_q1)
            ],
            SPECIALIST_Q2: [
                CallbackQueryHandler(bot.back_specialist_q1, pattern="^back_specialist_q1$"),
                CallbackQueryHandler(bot.specialist_q2_button, pattern="^proj_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voice_and_text_specialist_q2),
                MessageHandler(filters.VOICE, handle_voice_and_text_specialist_q2)
            ],
            SPECIALIST_Q3: [
                CallbackQueryHandler(bot.back_specialist_q2, pattern="^back_specialist_q2$"),
                CallbackQueryHandler(bot.specialist_q3_answer)
            ],
            SPECIALIST_Q4: [
                MessageHandler(filters.CONTACT, bot.specialist_q4_answer),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.specialist_q4_answer)
            ],
            RESEARCHER: [
                CallbackQueryHandler(bot.back_to_roles, pattern="^back_to_roles$"),
                CallbackQueryHandler(bot.researcher_info)
            ],
            CONTACT_SUPPORT: [
                CallbackQueryHandler(bot.back_to_roles, pattern="^back_to_roles$"),
                CallbackQueryHandler(bot.contact_support, pattern="^contact_support$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_voice_and_text_support),
                MessageHandler(filters.VOICE, handle_voice_and_text_support)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", bot.cancel),
            CallbackQueryHandler(bot.contact_support, pattern="^contact_support$")
        ],
    )
    
    application.add_handler(conv_handler)
    
    # Add roulette command handler
    application.add_handler(CommandHandler("roulette", bot.roulette_command))
    
    # Add web app data handler (for roulette results)
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, bot.handle_roulette_result))
    
    # Initialize database and register bot commands
    async def post_init(app: Application) -> None:
        """Initialize database and register bot commands"""
        await bot.initialize_db()
        commands = [
            BotCommand("start", "🚀 Начать работу с ботом"),
            BotCommand("roulette", "🎰 Крутить рулетку призов"),
            BotCommand("cancel", "❌ Отменить текущий опрос")
        ]
        await app.bot.set_my_commands(commands)
        logger.info("Bot commands registered in menu")
    
    application.post_init = post_init
    
    # Start bot
    logger.info("Starting Neuro-Connector Bot...")
    application.run_polling()

if __name__ == '__main__':
    main()
