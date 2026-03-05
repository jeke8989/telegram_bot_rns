#!/usr/bin/env python3
"""
Telegram Bot "Neuro-Connector" v3
Многоуровневая система нетворкинга для конференций
"""

import os
import logging
import uuid
from datetime import datetime, timedelta, timezone
import zoneinfo
from urllib.parse import quote
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
from zoom_client import ZoomClient
from lark_client import LarkClient
from kimai_client import KimaiClient
from report_generator import generate_team_report_excel
from client_report_generator import generate_client_report_pdf
from proposal_calculator import ProposalCalculator
from s3_client import S3Client

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
STAFF_MENU = 20
STAFF_ZOOM_TOPIC = 21
STAFF_ZOOM_DURATION = 22
STAFF_ZOOM_SCHEDULE = 23
STAFF_ZOOM_DATE = 24
STAFF_ZOOM_TIME = 25
STAFF_ZOOM_PARTICIPANTS = 26
ADMIN_VIEW_STAFF = 27
ADMIN_EDIT_NOTE = 28
STAFF_ZOOM_PROJECT = 29
STAFF_MY_MEETINGS = 30
ADMIN_REPORT_MENU = 31
ADMIN_TEAM_REPORT_DATES = 32
ADMIN_CLIENT_SELECT_CUSTOMER = 33
ADMIN_CLIENT_SELECT_PROJECTS = 34
ADMIN_CLIENT_REPORT_DATES = 35

CP_TYPE = 40
CP_BUDGET = 41
CP_BUDGET_AMOUNT = 42
CP_DESIGN = 43
CP_HOURLY_RATE = 44
CP_CLIENT_NAME = 45
CP_DESCRIPTION = 46
CP_CONFIRM = 47

ADMIN_STAFF_PROFILE = 50
ADMIN_SET_SPECIALTY = 51
ADMIN_SET_GRADE = 52

# Grade/specialty system for staff salary calculation
STAFF_SPECIALTIES: dict = {
    'dev': {
        'label': '💻 Dev (Разработчик)',
        'grades': {
            'junior_dev':       {'label': 'Junior Dev',        'rate': 1500},
            'junior_plus_dev':  {'label': 'Junior+ Dev',       'rate': 1850, 'transition': True},
            'middle_dev':       {'label': 'Middle Dev',        'rate': 2200},
            'middle_plus_dev':  {'label': 'Middle+ Dev',       'rate': 2450, 'transition': True},
            'senior_dev':       {'label': 'Senior Dev',        'rate': 2700},
            'senior_plus_dev':  {'label': 'Senior+ Dev',       'rate': 3000, 'transition': True},
            'lead_dev':         {'label': 'Lead Dev',          'rate': 3200},
        },
    },
    'designer': {
        'label': '🎨 Designer (Дизайнер)',
        'grades': {
            'junior_designer':  {'label': 'Junior Designer',   'rate': 1200},
            'middle_designer':  {'label': 'Middle Designer',   'rate': 1800},
            'senior_designer':  {'label': 'Senior Designer',   'rate': 2400},
        },
    },
    'qa': {
        'label': '🔍 QA (Тестировщик)',
        'grades': {
            'junior_qa':        {'label': 'Junior QA',         'rate': 1000},
            'middle_qa':        {'label': 'Middle QA',         'rate': 1500},
            'senior_qa':        {'label': 'Senior QA',         'rate': 2000},
        },
    },
}


def _get_grade_info(grade_key: str) -> dict | None:
    """Return grade data dict (label, rate, specialty_key, specialty_label) or None."""
    for spec_key, spec in STAFF_SPECIALTIES.items():
        if grade_key in spec['grades']:
            return {
                **spec['grades'][grade_key],
                'specialty_key': spec_key,
                'specialty_label': spec['label'],
            }
    return None


def _fmt_number_inline(n: float, currency: str = "$") -> str:
    """Format number with currency for inline text."""
    if currency == "$":
        return f"{n:,.0f}$".replace(",", " ")
    return f"{n:,.0f}₽".replace(",", " ")


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
        
        # Zoom + Lark clients (optional, only if configured)
        self.zoom: ZoomClient | None = None
        self.lark: LarkClient | None = None
        if self.config.zoom_account_id and self.config.zoom_client_id:
            self.zoom = ZoomClient(
                self.config.zoom_account_id,
                self.config.zoom_client_id,
                self.config.zoom_client_secret,
            )
        if self.config.lark_app_id and self.config.lark_app_secret:
            self.lark = LarkClient(
                self.config.lark_app_id,
                self.config.lark_app_secret,
                self.config.lark_group_chat_id,
            )
        self.kimai: KimaiClient | None = None
        if self.config.kimai_url and self.config.kimai_api_token:
            self.kimai = KimaiClient(
                self.config.kimai_url,
                self.config.kimai_api_token,
            )
        
        self.proposal_calculator = ProposalCalculator(self.config.openrouter_api_key)
    
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
        """Start command - show role selection, staff/admin menu, or handle invite deep link"""
        user = update.effective_user
        logger.info(f"User {user.id} started the bot")
        
        await self.initialize_db()
        
        # Save user to database
        await self.db.save_user(
            telegram_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            language_code=user.language_code
        )

        # Handle deep-links
        if context.args and len(context.args) > 0:
            arg = context.args[0]

            # Web app login: /start weblogin
            if arg == "weblogin":
                role = await self.db.get_user_role(user.id)
                webapp_url = self.config.webapp_url or ""

                if role == 'seller':
                    next_page = '/seller'
                elif role in ('staff', 'admin'):
                    next_page = '/projects'
                else:
                    client = await self.db.get_client_by_telegram_id(user.id)
                    if client and client.get('cabinet_token'):
                        next_page = f"/cabinet/{client['cabinet_token']}"
                    else:
                        next_page = '/my-cabinet'

                miniapp_url = f"{webapp_url}/login?next={quote(next_page)}"

                session_token = uuid.uuid4().hex
                note = ''
                if role in ('staff', 'admin', 'seller'):
                    note = await self.db.get_staff_note(user.id) or ''
                await self.db.create_web_session(
                    token=session_token,
                    telegram_id=user.id,
                    first_name=user.first_name or '',
                    username=user.username or '',
                    role=role,
                    note=note,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=3),
                )
                browser_url = f"{webapp_url}/auth/callback?token={session_token}&next={quote(next_page)}"

                app_label = "📱 Открыть в приложении" if role in ('staff', 'admin', 'seller') else "📱 Личный кабинет"
                browser_label = "🌐 Открыть в браузере"
                await update.message.reply_text(
                    "✅ <b>Авторизация подтверждена</b>\n\n"
                    "Выберите способ входа:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(app_label, web_app=WebAppInfo(url=miniapp_url))],
                        [InlineKeyboardButton(browser_label, url=browser_url)],
                    ]),
                    parse_mode='HTML',
                )
                if role in ('staff', 'admin', 'seller'):
                    return STAFF_MENU
                client = await self.db.get_client_by_telegram_id(user.id)
                if client:
                    context.user_data['is_client'] = True
                    context.user_data['client_id'] = client['id']
                    return CONTACT_SUPPORT
                return CHOOSING_ROLE

            # Handle invite deep-link: /start invite_<token>
            if arg.startswith("invite_"):
                token = arg[len("invite_"):]
                link = await self.db.get_invite_link_by_token(token)
                if link:
                    target_role = link.get('target_role', 'staff')
                    if target_role not in ('staff', 'seller', 'user'):
                        target_role = 'staff'

                    prev_role = await self.db.get_user_role(user.id)
                    is_new_member = prev_role not in ('staff', 'admin', 'seller')

                    await self.db.update_user_role(user.id, target_role)

                    role_labels = {
                        'staff': 'сотрудник',
                        'seller': 'партнёр по продажам',
                        'user': 'пользователь',
                    }
                    role_label = role_labels.get(target_role, target_role)

                    context.user_data['is_staff'] = target_role in ('staff', 'seller')
                    context.user_data['is_admin'] = False
                    context.user_data['is_seller'] = target_role == 'seller'

                    logger.info(f"User {user.id} assigned role '{target_role}' via invite (token={token})")
                    await update.message.reply_text(
                        f"✅ Вы добавлены как <b>{role_label}</b> компании <b>{self.config.company_name}</b>!",
                        parse_mode='HTML',
                    )

                    if is_new_member:
                        admins = await self.db.get_admin_users()
                        name = user.first_name or ""
                        if user.last_name:
                            name += f" {user.last_name}"
                        uname = f" (@{user.username})" if user.username else ""
                        for adm in admins:
                            try:
                                await context.bot.send_message(
                                    chat_id=adm['telegram_id'],
                                    text=(
                                        f"👤 <b>Новый {role_label} зарегистрирован</b>\n\n"
                                        f"Имя: <b>{name}</b>{uname}\n"
                                        f"ID: <code>{user.id}</code>"
                                    ),
                                    parse_mode='HTML',
                                )
                            except Exception as e:
                                logger.error(f"Failed to notify admin {adm['telegram_id']}: {e}")

                    if target_role in ('staff', 'seller'):
                        return await self.show_staff_menu(update, context, via_message=True)
                else:
                    logger.warning(f"Invalid invite token from user {user.id}: {token}")

            # Handle proposal deep-link: /start proposal_<token>
            if arg.startswith("proposal_"):
                proposal_token = arg[len("proposal_"):]
                try:
                    proposal = await self.db.get_commercial_proposal(proposal_token)
                    if proposal:
                        project_name = proposal.get('project_name', 'Проект')
                        proposal_url = f"{self.config.webapp_url}/proposal/{proposal_token}"

                        # Staff/admin should not become clients or generate leads
                        staff_ids = await self.db.get_staff_telegram_ids()
                        is_staff_user = user.id in staff_ids

                        if is_staff_user:
                            # Staff: just show cabinet link for the existing client
                            client_id = proposal.get('client_id')
                            if client_id:
                                client = await self.db.get_client(client_id)
                            else:
                                client = None
                            if client and client.get('cabinet_token'):
                                cabinet_url = f"{self.config.webapp_url}/cabinet/{client['cabinet_token']}"
                                keyboard = [[InlineKeyboardButton(
                                    "📂 Кабинет клиента", url=cabinet_url
                                )]]
                                await update.message.reply_text(
                                    f"📋 Проект: <b>«{project_name}»</b>\n\n"
                                    f"Вы открыли как сотрудник.",
                                    parse_mode='HTML',
                                    reply_markup=InlineKeyboardMarkup(keyboard),
                                )
                            else:
                                await update.message.reply_text(
                                    f"📋 Проект: <b>«{project_name}»</b>\n\n"
                                    f"К этому КП пока не привязан клиент.",
                                    parse_mode='HTML',
                                )
                            return await self.show_staff_menu(update, context, via_message=True)

                        name = user.first_name or ""
                        if user.last_name:
                            name += f" {user.last_name}"
                        uname = f" (@{user.username})" if user.username else ""

                        client = await self.db.get_client_by_telegram_id(user.id)
                        if not client:
                            client = await self.db.create_client_from_telegram(
                                telegram_id=user.id,
                                first_name=user.first_name,
                                last_name=user.last_name,
                                username=user.username,
                                proposal_token=proposal_token,
                            )
                        else:
                            if not proposal.get('client_id'):
                                await self.db.update_commercial_proposal(
                                    proposal_token, client_id=client['id']
                                )

                        cabinet_token = client.get('cabinet_token', '')
                        cabinet_url = f"{self.config.webapp_url}/cabinet/{cabinet_token}"

                        keyboard = [[InlineKeyboardButton(
                            "📂 Открыть кабинет проекта", url=cabinet_url
                        )]]

                        await update.message.reply_text(
                            f"👋 <b>Добро пожаловать!</b>\n\n"
                            f"Вы подключились к проекту <b>«{project_name}»</b>.\n\n"
                            f"В личном кабинете вы найдёте подробности проекта "
                            f"и сможете общаться с командой.\n\n"
                            f"💬 Также вы можете писать сообщения прямо сюда — "
                            f"мы обязательно ответим!",
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup(keyboard),
                        )

                        context.user_data['is_client'] = True
                        context.user_data['client_id'] = client['id']

                        group_id = self.config.support_group_id
                        if group_id:
                            try:
                                await context.bot.send_message(
                                    chat_id=group_id,
                                    text=(
                                        "🆕 <b>Новый лид из КП!</b>\n\n"
                                        f"👤 <b>{name}</b>{uname}\n"
                                        f"🆔 <code>{user.id}</code>\n"
                                        f"📋 Проект: <b>{project_name}</b>\n"
                                        f"🔗 <a href=\"{proposal_url}\">Открыть КП</a>\n"
                                        f"👤 <a href=\"{self.config.webapp_url}/client/{client['id']}\">Карточка клиента</a>"
                                    ),
                                    parse_mode='HTML',
                                    disable_web_page_preview=True,
                                )
                            except Exception as e:
                                logger.error(f"Failed to send proposal notification to group: {e}")

                        logger.info(f"Client {client['id']} created/linked from proposal {proposal_token}")
                        return CONTACT_SUPPORT
                except Exception as e:
                    logger.error(f"Error handling proposal deep link: {e}", exc_info=True)

            # Handle client registration deep-link: /start client_<cabinet_token>
            if arg.startswith("client_"):
                cabinet_token = arg[len("client_"):]
                try:
                    staff_ids = await self.db.get_staff_telegram_ids()
                    if user.id in staff_ids:
                        client = await self.db.get_client_by_cabinet_token(cabinet_token)
                        if client:
                            cabinet_url = f"{self.config.webapp_url}/cabinet/{cabinet_token}"
                            await update.message.reply_text(
                                f"📋 Вы открыли ссылку регистрации клиента "
                                f"<b>{client.get('first_name', '')} "
                                f"{client.get('last_name', '')}</b> как сотрудник.",
                                parse_mode='HTML',
                                reply_markup=InlineKeyboardMarkup([[
                                    InlineKeyboardButton("📂 Кабинет клиента", url=cabinet_url)
                                ]]),
                            )
                        else:
                            await update.message.reply_text(
                                "❌ Ссылка недействительна или клиент не найден.",
                                parse_mode='HTML',
                            )
                        return await self.show_staff_menu(update, context, via_message=True)

                    existing_client = await self.db.get_client_by_telegram_id(user.id)
                    if existing_client and existing_client.get('cabinet_token') == cabinet_token:
                        cabinet_url = f"{self.config.webapp_url}/cabinet/{cabinet_token}"
                        await update.message.reply_text(
                            f"👋 <b>С возвращением!</b>\n\n"
                            f"Вы уже зарегистрированы в системе.\n"
                            f"Откройте личный кабинет, чтобы увидеть актуальную информацию.",
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("📂 Мой кабинет", url=cabinet_url)],
                            ]),
                        )
                        context.user_data['is_client'] = True
                        context.user_data['client_id'] = existing_client['id']
                        return CONTACT_SUPPORT

                    client = await self.db.link_telegram_to_client(
                        cabinet_token=cabinet_token,
                        telegram_id=user.id,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        username=user.username,
                    )
                    if not client:
                        await update.message.reply_text(
                            "❌ Ссылка регистрации недействительна или уже использована.",
                            parse_mode='HTML',
                        )
                        return CHOOSING_ROLE

                    cabinet_url = f"{self.config.webapp_url}/cabinet/{cabinet_token}"

                    banner_path = Path(__file__).parent / "assets" / "welcome_client_banner.png"
                    if banner_path.exists():
                        with open(banner_path, 'rb') as photo:
                            await update.message.reply_photo(
                                photo=photo,
                                caption=(
                                    f"🎉 <b>Добро пожаловать в НейроСофт!</b>\n\n"
                                    f"Вы успешно зарегистрированы в клиентском портале.\n\n"
                                    f"📂 <b>Ваш личный кабинет активирован</b>\n"
                                    f"Здесь вы найдёте:\n"
                                    f"• Коммерческие предложения\n"
                                    f"• Информацию о проектах\n"
                                    f"• Прямую связь с командой\n\n"
                                    f"💬 Также вы можете писать нам прямо в этот чат —\n"
                                    f"мы обязательно ответим!"
                                ),
                                parse_mode='HTML',
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("📂 Открыть личный кабинет", url=cabinet_url)],
                                    [InlineKeyboardButton(
                                        "🌐 Войти через сайт",
                                        url=f"https://t.me/{context.bot.username}?start=weblogin"
                                    )],
                                ]),
                            )
                    else:
                        await update.message.reply_text(
                            f"🎉 <b>Добро пожаловать в НейроСофт!</b>\n\n"
                            f"Вы успешно зарегистрированы в клиентском портале.\n\n"
                            f"📂 <b>Ваш личный кабинет активирован</b>\n"
                            f"Здесь вы найдёте:\n"
                            f"• Коммерческие предложения\n"
                            f"• Информацию о проектах\n"
                            f"• Прямую связь с командой\n\n"
                            f"💬 Также вы можете писать нам прямо в этот чат —\n"
                            f"мы обязательно ответим!",
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("📂 Открыть личный кабинет", url=cabinet_url)],
                                [InlineKeyboardButton(
                                    "🌐 Войти через сайт",
                                    url=f"https://t.me/{context.bot.username}?start=weblogin"
                                )],
                            ]),
                        )

                    context.user_data['is_client'] = True
                    context.user_data['client_id'] = client['id']

                    client_name = user.first_name or ""
                    if user.last_name:
                        client_name += f" {user.last_name}"
                    uname = f" (@{user.username})" if user.username else ""

                    group_id = self.config.support_group_id
                    if group_id:
                        try:
                            await context.bot.send_message(
                                chat_id=group_id,
                                text=(
                                    "🆕 <b>Новый клиент зарегистрирован!</b>\n\n"
                                    f"👤 <b>{client_name}</b>{uname}\n"
                                    f"🆔 <code>{user.id}</code>\n"
                                    f"🏢 {client.get('company') or '—'}\n"
                                    f"👤 <a href=\"{self.config.webapp_url}/client/"
                                    f"{client.get('uuid')}\">Карточка клиента</a>"
                                ),
                                parse_mode='HTML',
                                disable_web_page_preview=True,
                            )
                        except Exception as e:
                            logger.error(f"Failed to send client registration notification: {e}")

                    logger.info(
                        f"Client {client['id']} registered via deep link "
                        f"(tg={user.id}, token={cabinet_token})"
                    )
                    return CONTACT_SUPPORT
                except Exception as e:
                    logger.error(f"Error handling client deep link: {e}", exc_info=True)

        # Staff / admin users get their own welcome screen
        role = await self.db.get_user_role(user.id)
        if role == "admin":
            context.user_data['is_staff'] = True
            context.user_data['is_admin'] = True
            context.user_data['is_seller'] = False
            return await self.show_staff_menu(update, context, via_message=True)
        if role == "seller":
            context.user_data['is_staff'] = True
            context.user_data['is_admin'] = False
            context.user_data['is_seller'] = True
            return await self.show_staff_menu(update, context, via_message=True)
        if role == "staff":
            context.user_data['is_staff'] = True
            context.user_data['is_admin'] = False
            context.user_data['is_seller'] = False
            return await self.show_staff_menu(update, context, via_message=True)
        
        welcome_caption = (
            f"👋 <b>Привет! Я — AI-бот от {self.config.company_name}</b>\n\n"
            f"Я анализирую вашу проблему и <b>предложу конкретное решение</b> за 2 минуты.\n\n"
            f"🎯 Отвечу на 3–4 вопроса\n"
            f"🧠 Проанализирую вашу ситуацию\n"
            f"✨ Подготовлю персональные рекомендации\n\n"
            f"🎰 <b>Бонус:</b> В конце вас ждёт сюрприз — рулетка с реальным денежным призом "
            f"до <b>30 000 ₽</b> на услуги нашей компании!\n\n"
            f"Выберите, что вам ближе:"
        )

        keyboard = [
            [InlineKeyboardButton("🚀 У меня есть бизнес", callback_data="role_entrepreneur")],
            [InlineKeyboardButton("💡 У меня есть идея/стартап", callback_data="role_startupper")],
            [InlineKeyboardButton("💻 Я разработчик/специалист", callback_data="role_specialist")],
            [InlineKeyboardButton("📈 Ищу интересный проект", callback_data="role_researcher")],
            [InlineKeyboardButton("💬 Связаться с сотрудником", callback_data="contact_support")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        banner_path = Path(__file__).parent / "assets" / "welcome_client_banner.png"
        if banner_path.exists():
            with open(banner_path, 'rb') as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=welcome_caption,
                    parse_mode='HTML',
                    reply_markup=reply_markup,
                )
        else:
            await update.message.reply_text(
                welcome_caption, reply_markup=reply_markup, parse_mode='HTML'
            )
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
            context=context,
            username=update.effective_user.username
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
            context=context,
            username=update.effective_user.username
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
            welcome_msg = await self.ai.generate_startup_recommendations(
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
            context=context,
            username=update.effective_user.username
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
                # Remove @ if present and create clickable link
                tg_username = self.config.company_telegram.lstrip('@')
                contact_parts.append(f"\n📱 Telegram: [@{tg_username}](https://t.me/{tg_username})")
            
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
            context=context,
            username=user.username
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
                # Remove @ if present and create clickable link
                tg_username = self.config.company_telegram.lstrip('@')
                caption_parts.append(f"\n📱 [@{tg_username}](https://t.me/{tg_username})")
            
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
        
        try:
            await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            # If edit fails, send new message
            logger.warning(f"Failed to edit message: {e}. Sending new message instead.")
            await query.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
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

    
    async def send_new_lead_notification(self, user_id: int, user_name: str, role: str, context: ContextTypes.DEFAULT_TYPE, username: str = None):
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
            
            # Use username from parameter if provided, otherwise try from db
            display_username = username if username else (db_user_info.get('username', 'None') if db_user_info else 'None')
            
            # Escape HTML special characters in user data
            def escape_html(text):
                if text is None:
                    return 'Не указано'
                text = str(text)
                return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            phone = escape_html(db_user_info.get('phone_number')) if db_user_info else 'Не указан'
            email = escape_html(db_user_info.get('email')) if db_user_info else 'Не указан'
            company = escape_html(db_user_info.get('company')) if db_user_info else 'Не указана'
            position = escape_html(db_user_info.get('position')) if db_user_info else 'Не указана'
            
            notification_text = f"""
🎉 <b>НОВАЯ ЗАЯВКА!</b>

👤 <b>Пользователь:</b>
├ ID: <code>{user_id}</code>
├ Имя: {escape_html(user_name)}
├ Username: @{escape_html(display_username)}
└ Роль: {role_map.get(role, 'Не указана')}

📋 <b>Данные анкеты:</b>
{self._format_user_survey_data(context.user_data, role)}

📞 <b>Контакты:</b>
├ Телефон: {phone}
├ Email: {email}
├ Компания: {company}
└ Должность: {position}

🔗 <b>Ссылка:</b> <a href="tg://user?id={user_id}">Открыть диалог</a>
            """
            
            await context.bot.send_message(
                chat_id=self.config.support_group_id,
                text=notification_text,
                parse_mode='HTML'
            )
            
            logger.info(f"New lead notification sent for user {user_id} to group {self.config.support_group_id}")
        except Exception as e:
            logger.error(f"Failed to send new lead notification: {e}", exc_info=True)
    
    def _format_user_survey_data(self, user_data: dict, role: str) -> str:
        """Format user survey data for notification"""
        # Escape HTML special characters
        def escape_html(text):
            if text is None:
                return 'Не указано'
            text = str(text)
            return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        if role == 'entrepreneur':
            return f"""├ Проблема: {escape_html(user_data.get('process_pain', 'Не указано'))}
├ Потери времени: {escape_html(user_data.get('time_lost', 'Не указано'))}
└ Отдел: {escape_html(user_data.get('department_affected', 'Не указано'))}"""
        elif role == 'startupper':
            return f"""├ Проблема: {escape_html(user_data.get('problem_solved', 'Не указано'))}
├ Стадия: {escape_html(user_data.get('current_stage', 'Не указано'))}
└ Барьер: {escape_html(user_data.get('main_barrier', 'Не указано'))}"""
        elif role == 'specialist':
            return f"""├ Навык: {escape_html(user_data.get('main_skill', 'Не указано'))}
├ Проекты: {escape_html(user_data.get('project_type', 'Не указано'))}
└ Интерес: {escape_html(user_data.get('interest', 'Не указано'))}"""
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
            
            # Escape HTML special characters
            def escape_html(text):
                if text is None:
                    return 'Не указано'
                text = str(text)
                return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            phone = escape_html(db_user_info.get('phone_number')) if db_user_info else 'Не указан'
            email = escape_html(db_user_info.get('email')) if db_user_info else 'Не указан'
            company = escape_html(db_user_info.get('company')) if db_user_info else 'Не указана'
            position = escape_html(db_user_info.get('position')) if db_user_info else 'Не указана'
            website = escape_html(db_user_info.get('website')) if db_user_info else 'Не указан'
            username_display = escape_html(user.username) if user.username else 'не указан'
            
            # Send notification to support group
            calculation_request = f"""
💰 <b>ЗАПРОС РАСЧЕТА СТОИМОСТИ</b>

👤 <b>Пользователь:</b>
├ ID: <code>{user_id}</code>
├ Имя: {escape_html(user.first_name)} {escape_html(user.last_name or '')}
├ Username: @{username_display}
└ Роль: {role_map.get(role, 'Не указана')}

📋 <b>Данные анкеты:</b>
{self._format_user_survey_data(context.user_data, role)}

📞 <b>Контакты:</b>
├ Телефон: {phone}
├ Email: {email}
├ Компания: {company}
├ Должность: {position}
└ Сайт: {website}

🔗 <b>Ссылка:</b> <a href="tg://user?id={user_id}">Открыть диалог</a>

⚠️ <b>Пользователь ждет расчет стоимости проекта!</b>
            """
            
            await context.bot.send_message(
                chat_id=self.config.support_group_id,
                text=calculation_request,
                parse_mode='HTML'
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
        try:
            await query.edit_message_text(
                text="""
💬 **Связь с сотрудником**

Опишите ваш вопрос или проблему, и наш специалист свяжется с вами в ближайшее время.

Напишите ваше сообщение текстом или отправьте голосовое сообщение 🎙️
                """,
                parse_mode='Markdown'
            )
        except Exception as e:
            # If edit fails (e.g., message with inline keyboard deleted), send new message
            logger.warning(f"Failed to edit message: {e}. Sending new message instead.")
            await query.message.reply_text(
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

        # Save to client_messages if this user is a client
        try:
            client = await self.db.get_client_by_telegram_id(user.id)
            if client and user_message:
                await self.db.save_client_message(
                    client_id=client['id'],
                    direction='in',
                    sender_name=client.get('name', user.first_name),
                    message=user_message,
                    telegram_message_id=update.message.message_id if update.message else None,
                )
        except Exception as e:
            logger.error(f"Failed to save client message: {e}")

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
    
    # ---- Staff / Zoom methods ----

    async def handle_staff_secret(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Activate staff mode when secret code is entered."""
        user = update.effective_user
        await self.initialize_db()
        await self.db.update_user_role(user.id, "staff")
        logger.info(f"User {user.id} ({user.first_name}) activated staff mode")
        context.user_data['is_staff'] = True
        context.user_data['is_admin'] = False
        context.user_data['is_seller'] = False
        return await self.show_staff_menu(update, context, via_message=True)

    async def handle_admin_secret(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Activate admin mode when admin code is entered."""
        user = update.effective_user
        await self.initialize_db()
        await self.db.update_user_role(user.id, "admin")
        logger.info(f"User {user.id} ({user.first_name}) activated admin mode")
        context.user_data['is_staff'] = True
        context.user_data['is_admin'] = True
        context.user_data['is_seller'] = False
        return await self.show_staff_menu(update, context, via_message=True)

    async def show_staff_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, via_message: bool = False):
        """Show beautiful staff/admin/seller welcome screen."""
        user = update.effective_user
        first_name = user.first_name or "Сотрудник"
        is_admin = context.user_data.get('is_admin', False)
        is_seller = context.user_data.get('is_seller', False)

        if is_admin:
            text = (
                f"👋 Привет, <b>{first_name}</b>!\n\n"
                f"🏢 <b>{self.config.company_name}</b>\n\n"
                "У тебя <b>полный доступ</b> к системе.\n\n"
                "🎯 <b>Что можно делать:</b>\n"
                "  • Создавать и управлять встречами\n"
                "  • Работать с проектами и клиентами\n"
                "  • Управлять командой сотрудников\n"
                "  • Формировать отчёты и КП\n\n"
                "⬇️ <i>Выберите действие:</i>"
            )
        elif is_seller:
            text = (
                f"👋 Привет, <b>{first_name}</b>!\n\n"
                f"🏢 <b>{self.config.company_name}</b>\n\n"
                "Добро пожаловать в панель продаж.\n\n"
                "🎯 <b>Что можно делать:</b>\n"
                "  • Создавать коммерческие предложения\n"
                "  • Отслеживать свои КП\n\n"
                "⬇️ <i>Выберите действие:</i>"
            )
        else:
            text = (
                f"👋 Привет, <b>{first_name}</b>!\n\n"
                f"🏢 <b>{self.config.company_name}</b>\n\n"
                "Добро пожаловать в рабочий портал.\n\n"
                "🎯 <b>Что можно делать:</b>\n"
                "  • Создавать встречи и записи\n"
                "  • Работать с проектами\n"
                "  • Открыть портал проектов\n\n"
                "⬇️ <i>Выберите действие:</i>"
            )

        keyboard = []

        if is_seller:
            keyboard.append(
                [InlineKeyboardButton("📄  Коммерческое предложение", callback_data="admin_cp_start")]
            )
            seller_url = f"{self.config.webapp_url}/seller" if self.config.webapp_url else None
            if seller_url:
                keyboard.append(
                    [InlineKeyboardButton("🌐  Мои КП", web_app=WebAppInfo(url=seller_url))]
                )
        else:
            keyboard.append(
                [InlineKeyboardButton("📹  Создать встречу", callback_data="staff_create_zoom")]
            )
            keyboard.append(
                [InlineKeyboardButton("📋  Мои встречи", callback_data="staff_my_meetings")]
            )
            portal_url = f"{self.config.webapp_url}/projects" if self.config.webapp_url else None
            if portal_url:
                keyboard.append(
                    [InlineKeyboardButton("🌐  Портал проектов", web_app=WebAppInfo(url=portal_url))]
                )

        if is_admin:
            keyboard.append(
                [InlineKeyboardButton("👥  Сотрудники", callback_data="admin_view_staff")]
            )
            keyboard.append(
                [InlineKeyboardButton("🔗  Пригласить сотрудника", callback_data="admin_create_invite")]
            )
            if self.kimai:
                keyboard.append(
                    [InlineKeyboardButton("📊  Создать отчёт", callback_data="admin_report_menu")]
                )
            keyboard.append(
                [InlineKeyboardButton("📄  Коммерческое предложение", callback_data="admin_cp_start")]
            )
        reply_markup = InlineKeyboardMarkup(keyboard)

        if via_message:
            banner_path = Path(__file__).parent / "assets" / "welcome_client_banner.png"
            if banner_path.exists():
                with open(banner_path, 'rb') as photo:
                    await update.message.reply_photo(photo=photo)
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            query = update.callback_query
            await query.answer()
            try:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
            except Exception:
                await query.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return STAFF_MENU

    async def staff_my_meetings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show list of scheduled (not yet ended) meetings for this user."""
        query = update.callback_query
        await query.answer()
        user = query.from_user

        host_meetings = await self.db.get_host_upcoming_meetings(user.id)
        guest_meetings = await self.db.get_participant_upcoming_meetings(user.id)

        all_meetings = [('host', m) for m in host_meetings] + [('guest', m) for m in guest_meetings]
        all_meetings.sort(key=lambda x: x[1].get('start_time') or datetime.max.replace(tzinfo=None))

        if not all_meetings:
            await query.edit_message_text(
                "📋 <b>Мои встречи</b>\n\n"
                "У вас пока нет запланированных встреч.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
            )
            return STAFF_MY_MEETINGS

        lines = ["📋 <b>Мои встречи</b>\n"]
        keyboard = []

        for i, (role, m) in enumerate(all_meetings, 1):
            mid = m['meeting_id']
            topic = m.get('topic', 'Встреча')
            date_label = self._format_date_label(
                m['start_time'].isoformat() if m.get('start_time') else None
            )
            duration_label = self._duration_label(m.get('duration', 0))
            role_icon = "👑" if role == 'host' else "👤"

            lines.append(
                f"{i}. {role_icon} <b>{topic}</b>\n"
                f"    📅 {date_label}  ·  ⏱ {duration_label}"
            )

            link_url = m.get('start_url') if role == 'host' else m.get('join_url')
            link_label = "🎬 Начать встречу" if role == 'host' else "🔗 Ссылка"

            if link_url:
                keyboard.append([
                    InlineKeyboardButton(link_label, url=link_url),
                ])
            if role == 'host':
                keyboard.append([
                    InlineKeyboardButton("⚡️ Перенести", callback_data=f"zoom_reschedule_{mid}"),
                    InlineKeyboardButton("🗑 Отменить", callback_data=f"zoom_cancel_{mid}"),
                ])
            if i < len(all_meetings):
                lines.append("─────────────────────")

        keyboard.append([InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")])

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML',
        )
        return STAFF_MY_MEETINGS

    async def staff_zoom_cancel_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ask for confirmation before cancelling a meeting."""
        query = update.callback_query
        await query.answer()

        try:
            meeting_id = int(query.data.replace("zoom_cancel_", ""))
        except Exception:
            return STAFF_MY_MEETINGS

        meeting = await self.db.get_zoom_meeting(meeting_id)
        if not meeting:
            await query.edit_message_text(
                "❌ Встреча не найдена.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")]]),
            )
            return STAFF_MENU

        if meeting.get('host_telegram_id') != query.from_user.id:
            await query.edit_message_text(
                "⛔️ Отменить встречу может только её создатель.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")]]),
            )
            return STAFF_MENU

        topic = meeting.get('topic', 'Встреча')
        date_label = self._format_date_label(
            meeting['start_time'].isoformat() if meeting.get('start_time') else None
        )

        await query.edit_message_text(
            f"⚠️ <b>Отмена встречи</b>\n\n"
            f"Вы уверены, что хотите отменить встречу?\n\n"
            f"📌 <b>{topic}</b>\n"
            f"📅 {date_label}\n\n"
            f"Всем приглашённым участникам будет отправлено уведомление.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Да, отменить", callback_data=f"zoom_cancel_yes_{meeting_id}"),
                    InlineKeyboardButton("↩️ Нет", callback_data="staff_my_meetings"),
                ],
            ]),
            parse_mode='HTML',
        )
        return STAFF_MY_MEETINGS

    async def staff_zoom_cancel_execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Actually cancel the meeting: notify participants, delete from Zoom, update Lark, delete from DB."""
        query = update.callback_query
        await query.answer()

        try:
            meeting_id = int(query.data.replace("zoom_cancel_yes_", ""))
        except Exception:
            return STAFF_MY_MEETINGS

        meeting = await self.db.get_zoom_meeting(meeting_id)
        if not meeting:
            await query.edit_message_text("❌ Встреча не найдена.")
            return STAFF_MENU

        if meeting.get('host_telegram_id') != query.from_user.id:
            await query.edit_message_text("⛔️ Отменить встречу может только её создатель.")
            return STAFF_MENU

        topic = meeting.get('topic', 'Встреча')
        date_label = self._format_date_label(
            meeting['start_time'].isoformat() if meeting.get('start_time') else None
        )
        duration_label = self._duration_label(meeting.get('duration', 0))
        host_name = query.from_user.first_name

        await query.edit_message_text("⏳ Отменяю встречу...")

        # 1. Notify participants in Telegram
        participants = await self.db.get_meeting_participants(meeting_id)
        for p in participants:
            p_id = p.get('telegram_id')
            if not p_id or p_id == query.from_user.id:
                continue
            try:
                await context.bot.send_message(
                    chat_id=p_id,
                    text=(
                        "🚫 <b>Встреча отменена</b>\n\n"
                        f"📌 <b>Тема:</b> {topic}\n"
                        f"📅 <b>Когда:</b> {date_label}\n"
                        f"👤 <b>Организатор:</b> {host_name}\n\n"
                        "Организатор отменил эту встречу."
                    ),
                    parse_mode='HTML',
                )
            except Exception as e:
                logger.warning(f"Failed to notify participant {p_id} about cancellation: {e}")

        # 2. Delete/replace Lark card
        if self.lark:
            try:
                old_lark_id = meeting.get('lark_message_id')
                if old_lark_id:
                    try:
                        await self.lark.delete_message(old_lark_id)
                    except Exception:
                        pass
                host_note = await self.db.get_staff_note(query.from_user.id)
                host_label = self._format_person_label(
                    first_name=host_name,
                    username=query.from_user.username,
                    note=host_note or None,
                )
                participants_list = []
                for p in participants:
                    note = await self.db.get_staff_note(p.get('telegram_id')) if p.get('telegram_id') else ""
                    participants_list.append({
                        'telegram_id': p.get('telegram_id'),
                        'first_name': p.get('first_name'),
                        'username': p.get('username'),
                        'note': note,
                    })
                await self.lark.send_meeting_cancelled_card(
                    topic=topic,
                    host_name=host_label,
                    start_time=date_label,
                    duration=meeting.get('duration', 0),
                    participants=participants_list if participants_list else None,
                )
            except Exception as e:
                logger.error(f"Failed to send Lark cancelled card for meeting {meeting_id}: {e}")

        # 3. Cancel reminders
        self._clear_meeting_reminder_jobs(context.job_queue, meeting_id)

        # 4. Delete from DB
        try:
            await self.db.delete_meeting(meeting_id)
        except Exception as e:
            logger.error(f"Failed to delete meeting {meeting_id} from DB: {e}")

        await query.edit_message_text(
            "✅ <b>Встреча отменена</b>\n\n"
            f"📌 {topic}\n"
            f"📅 {date_label}\n\n"
            "Все участники уведомлены.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Мои встречи", callback_data="staff_my_meetings")],
                [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
            ]),
            parse_mode='HTML',
        )
        return STAFF_MY_MEETINGS

    async def staff_create_zoom_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Staff clicked 'Create Zoom' — ask for meeting topic."""
        query = update.callback_query
        await query.answer()

        if not self.zoom:
            await query.edit_message_text("❌ Zoom не настроен. Обратитесь к администратору.")
            return STAFF_MENU

        await query.edit_message_text(
            "📹 <b>Создание Zoom-встречи</b>\n\n"
            "Введите тему встречи:",
            parse_mode='HTML',
        )
        return STAFF_ZOOM_TOPIC

    async def staff_zoom_topic_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Staff entered meeting topic — show duration buttons."""
        topic = update.message.text.strip()
        context.user_data['zoom_topic'] = topic

        keyboard = [
            [
                InlineKeyboardButton("15 мин", callback_data="zoom_dur_15"),
                InlineKeyboardButton("30 мин", callback_data="zoom_dur_30"),
            ],
            [
                InlineKeyboardButton("45 мин", callback_data="zoom_dur_45"),
                InlineKeyboardButton("1 час", callback_data="zoom_dur_60"),
            ],
            [
                InlineKeyboardButton("1 ч 30 мин", callback_data="zoom_dur_90"),
                InlineKeyboardButton("2 часа", callback_data="zoom_dur_120"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"📌 Тема: <b>{topic}</b>\n\n"
            "⏱ Выберите длительность встречи:",
            reply_markup=reply_markup,
            parse_mode='HTML',
        )
        return STAFF_ZOOM_DURATION

    async def staff_zoom_duration_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Staff selected duration — ask now or schedule."""
        query = update.callback_query
        await query.answer()

        duration = int(query.data.replace("zoom_dur_", ""))
        context.user_data['zoom_duration'] = duration
        topic = context.user_data.get('zoom_topic', 'Встреча')

        duration_label = f"{duration} мин"
        if duration >= 60:
            h, m = divmod(duration, 60)
            duration_label = f"{h} ч" + (f" {m} мин" if m else "")

        keyboard = [
            [InlineKeyboardButton("▶️  Начать сейчас", callback_data="zoom_schedule_now")],
            [InlineKeyboardButton("📅  Запланировать на...", callback_data="zoom_schedule_later")],
            [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
        ]

        await query.edit_message_text(
            f"📌 <b>Тема:</b> {topic}\n"
            f"⏱ <b>Длительность:</b> {duration_label}\n\n"
            "Когда провести встречу?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML',
        )
        return STAFF_ZOOM_SCHEDULE

    # --- Schedule: now ---

    async def staff_zoom_schedule_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User chose to start meeting now — go to participant selection."""
        query = update.callback_query
        await query.answer()
        context.user_data['zoom_start_time'] = None
        return await self._show_participant_selection(query, context)

    # --- Schedule: later → date picker ---

    async def staff_zoom_schedule_later(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User chose to schedule — show 7-day calendar."""
        query = update.callback_query
        await query.answer()
        return await self._show_date_picker(query, context)

    async def _show_date_picker(self, query, context):
        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        today = datetime.now(tz).date()
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        month_names = ["", "янв", "фев", "мар", "апр", "мая", "июн",
                       "июл", "авг", "сен", "окт", "ноя", "дек"]

        buttons = []

        # "Now" button only in reschedule mode
        if context.user_data.get('zoom_mode') == 'reschedule':
            buttons.append([InlineKeyboardButton("⚡️ Сейчас", callback_data="zoom_now")])

        row = []
        for i in range(7):
            d = today + timedelta(days=i)
            label = f"{day_names[d.weekday()]}, {d.day} {month_names[d.month]}"
            row.append(InlineKeyboardButton(label, callback_data=f"zoom_date_{d.isoformat()}"))
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")])

        await query.edit_message_text(
            "📅 <b>Выберите дату встречи:</b>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='HTML',
        )
        return STAFF_ZOOM_DATE

    async def staff_zoom_reschedule_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reschedule meeting to start immediately (now)."""
        query = update.callback_query
        await query.answer()
        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        now = datetime.now(tz)
        context.user_data['zoom_start_time'] = now.isoformat()
        return await self._reschedule_existing_meeting(query, context)

    # --- Date selected → time picker ---

    async def staff_zoom_date_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User picked a date — show time slots."""
        query = update.callback_query
        await query.answer()
        date_str = query.data.replace("zoom_date_", "")
        context.user_data['zoom_date'] = date_str
        return await self._show_time_picker(query, context, date_str)

    async def _show_time_picker(self, query, context, date_str):
        buttons = []
        row = []
        for hour in range(9, 22):
            for minute in (0, 30):
                t = f"{hour:02d}:{minute:02d}"
                row.append(InlineKeyboardButton(t, callback_data=f"zoom_time_{t}"))
                if len(row) == 4:
                    buttons.append(row)
                    row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("◀️ Назад к дате", callback_data="zoom_schedule_later")])
        buttons.append([InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")])

        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        d = datetime.fromisoformat(date_str)
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        month_names = ["", "янв", "фев", "мар", "апр", "мая", "июн",
                       "июл", "авг", "сен", "окт", "ноя", "дек"]
        date_label = f"{day_names[d.weekday()]}, {d.day} {month_names[d.month]}"

        await query.edit_message_text(
            f"📅 Дата: <b>{date_label}</b>\n\n"
            "🕐 <b>Выберите время (МСК):</b>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='HTML',
        )
        return STAFF_ZOOM_TIME

    # --- Time selected → participant selection ---

    async def staff_zoom_time_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User picked a time — combine with date and go to participants."""
        query = update.callback_query
        await query.answer()
        time_str = query.data.replace("zoom_time_", "")
        date_str = context.user_data.get('zoom_date')

        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        dt = datetime.fromisoformat(f"{date_str}T{time_str}:00")
        dt_aware = dt.replace(tzinfo=tz)
        context.user_data['zoom_start_time'] = dt_aware.isoformat()

        if context.user_data.get('zoom_mode') == 'reschedule':
            return await self._reschedule_existing_meeting(query, context)

        return await self._show_participant_selection(query, context)

    # --- Participant multi-select ---

    async def _show_participant_selection(self, query, context):
        user = query.from_user
        await self.initialize_db()
        staff_list = await self.db.get_staff_users(exclude_telegram_id=user.id)
        logger.info(f"Participant selection: found {len(staff_list)} staff for user {user.id}")

        # Fetch notes for all staff in bulk
        tids = [s['telegram_id'] for s in staff_list]
        notes = await self.db.get_staff_notes_bulk(tids) if tids else {}
        context.user_data['_staff_notes'] = notes

        context.user_data.setdefault('zoom_participants', set())
        context.user_data['_staff_list'] = staff_list
        return await self._render_participant_buttons(query, context)

    async def _render_participant_buttons(self, query, context):
        staff_list = context.user_data.get('_staff_list', [])
        selected = context.user_data.get('zoom_participants', set())
        notes = context.user_data.get('_staff_notes', {})

        header = "👥 <b>Выберите участников встречи:</b>\n\n"
        buttons = []
        if staff_list:
            for s in staff_list:
                tid = s['telegram_id']
                name = s.get('first_name') or s.get('username') or str(tid)
                last = s.get('last_name')
                if last:
                    name = f"{name} {last}"
                note = notes.get(tid, "")
                if note:
                    header += f"{'✅' if tid in selected else '◻️'} <b>{name}</b> — <i>{note}</i>\n"
                else:
                    header += f"{'✅' if tid in selected else '◻️'} <b>{name}</b>\n"
                prefix = "✅ " if tid in selected else "    "
                buttons.append([InlineKeyboardButton(
                    f"{prefix}{name}",
                    callback_data=f"zoom_participant_toggle_{tid}",
                )])
            header += "\nНажмите на имя, чтобы пригласить."
        else:
            header += "<i>Других сотрудников пока нет в боте.\nНажмите «Подтвердить» чтобы продолжить.</i>"

        count = len(selected)
        confirm_label = f"Подтвердить ({count})" if count else "Подтвердить"
        buttons.append([
            InlineKeyboardButton(f"✔️ {confirm_label}", callback_data="zoom_participants_confirm"),
            InlineKeyboardButton("⏩ Пропустить", callback_data="zoom_participants_skip"),
        ])
        buttons.append([InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")])

        await query.edit_message_text(
            header,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='HTML',
        )
        return STAFF_ZOOM_PARTICIPANTS

    async def staff_zoom_toggle_participant(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        tid = int(query.data.replace("zoom_participant_toggle_", ""))
        selected = context.user_data.setdefault('zoom_participants', set())
        if tid in selected:
            selected.discard(tid)
        else:
            selected.add(tid)
        return await self._render_participant_buttons(query, context)

    async def staff_zoom_participants_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        return await self._ask_project_link(query, context)

    async def staff_zoom_participants_skip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        context.user_data['zoom_participants'] = set()
        return await self._ask_project_link(query, context)

    async def _ask_project_link(self, query, context):
        """Ask user if they want to link the meeting to a project."""
        keyboard = [
            [InlineKeyboardButton("📁 Да, выбрать проект", callback_data="zoom_project_choose")],
            [InlineKeyboardButton("➡️ Без проекта", callback_data="zoom_project_skip")],
            [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
        ]
        await query.edit_message_text(
            "📁 <b>Привязать встречу к проекту?</b>\n\n"
            "Вы можете привязать эту встречу к существующему проекту "
            "или создать её без привязки.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML',
        )
        return STAFF_ZOOM_PROJECT

    async def staff_zoom_project_choose(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show list of projects to choose from."""
        query = update.callback_query
        await query.answer()

        is_admin = context.user_data.get('is_admin', False)
        try:
            if is_admin:
                projects = await self.db.get_all_projects()
            else:
                projects = await self.db.get_staff_visible_projects()
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")
            projects = []

        if not projects:
            keyboard = [
                [InlineKeyboardButton("➡️ Создать без проекта", callback_data="zoom_project_skip")],
                [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
            ]
            await query.edit_message_text(
                "📁 <b>Проектов пока нет</b>\n\n"
                "Создайте проект на странице любой встречи, "
                "а затем повторите создание встречи.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML',
            )
            return STAFF_ZOOM_PROJECT

        keyboard = []
        for p in projects:
            count = p.get('meeting_count', 0)
            label = f"📁 {p['name']}  ({count} 🎥)"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"zoom_project_pick_{p['id']}")])

        keyboard.append([InlineKeyboardButton("➡️ Без проекта", callback_data="zoom_project_skip")])
        keyboard.append([InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")])

        await query.edit_message_text(
            "📁 <b>Выберите проект</b>\n\n"
            "К какому проекту привязать эту встречу?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML',
        )
        return STAFF_ZOOM_PROJECT

    async def staff_zoom_project_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User picked a project — save it and create the meeting."""
        query = update.callback_query
        await query.answer()
        project_id = int(query.data.replace("zoom_project_pick_", ""))
        context.user_data['zoom_project_id'] = project_id
        return await self._create_meeting_and_invite(query, context)

    async def staff_zoom_project_skip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User skipped project selection — create meeting without project."""
        query = update.callback_query
        await query.answer()
        context.user_data.pop('zoom_project_id', None)
        return await self._create_meeting_and_invite(query, context)

    async def staff_zoom_reschedule_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start rescheduling flow for an existing meeting."""
        query = update.callback_query
        await query.answer()

        try:
            meeting_id = int(query.data.replace("zoom_reschedule_", ""))
        except Exception:
            await query.edit_message_text(
                "❌ Не удалось определить встречу для переноса.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")]]),
            )
            return STAFF_MENU

        meeting = await self.db.get_zoom_meeting(meeting_id)
        if not meeting:
            await query.edit_message_text(
                "❌ Встреча не найдена в базе.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")]]),
            )
            return STAFF_MENU

        if meeting.get('host_telegram_id') != query.from_user.id:
            await query.edit_message_text(
                "⛔️ Перенести встречу может только её создатель.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")]]),
            )
            return STAFF_MENU

        if meeting.get('status') != 'scheduled':
            await query.edit_message_text(
                "ℹ️ Перенос доступен только для встреч со статусом scheduled.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")]]),
            )
            return STAFF_MENU

        context.user_data['zoom_mode'] = 'reschedule'
        context.user_data['zoom_edit_meeting_id'] = meeting_id
        context.user_data['zoom_duration'] = int(meeting.get('duration') or 60)
        context.user_data['zoom_topic'] = meeting.get('topic') or 'Встреча'
        return await self._show_date_picker(query, context)

    async def _reschedule_existing_meeting(self, query, context):
        """Apply selected slot to an existing Zoom meeting and sync DB/Lark."""
        if not self.zoom:
            await query.edit_message_text(
                "❌ Zoom не настроен. Перенос недоступен.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")]]),
            )
            return STAFF_MENU

        meeting_id = context.user_data.get('zoom_edit_meeting_id')
        start_time = context.user_data.get('zoom_start_time')
        if not meeting_id or not start_time:
            await query.edit_message_text(
                "❌ Не удалось перенести встречу: отсутствуют данные.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")]]),
            )
            return STAFF_MENU

        meeting = await self.db.get_zoom_meeting(int(meeting_id))
        if not meeting:
            await query.edit_message_text(
                "❌ Встреча не найдена в базе.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")]]),
            )
            return STAFF_MENU

        duration = int(meeting.get('duration') or context.user_data.get('zoom_duration') or 60)
        topic = meeting.get('topic') or 'Встреча'

        await query.edit_message_text("⏳ Переношу встречу в Zoom...")

        try:
            await self.zoom.update_meeting(int(meeting_id), start_time, duration)
            await self.db.update_meeting_schedule(
                int(meeting_id),
                datetime.fromisoformat(start_time),
                duration,
            )

            date_label = self._format_date_label(start_time)
            duration_label = self._duration_label(duration)
            join_url = meeting.get('join_url', '')
            start_url = meeting.get('start_url', '')
            password = meeting.get('password') or ''

            # Notify participants about reschedule
            participants = await self.db.get_meeting_participants(int(meeting_id))
            host_id = meeting.get('host_telegram_id')
            host_name = query.from_user.first_name
            for p in participants:
                p_id = p.get('telegram_id')
                if not p_id or p_id == query.from_user.id:
                    continue
                try:
                    await context.bot.send_message(
                        chat_id=p_id,
                        text=(
                            "🔄 <b>Встреча перенесена</b>\n\n"
                            f"📌 <b>Тема:</b> {topic}\n"
                            f"📅 <b>Новое время:</b> {date_label}\n"
                            f"⏱ <b>Длительность:</b> {duration_label}\n"
                            f"👤 <b>Организатор:</b> {host_name}\n\n"
                            f"🔗 <b>Ссылка:</b> {join_url}"
                            + (f"\n🔑 <b>Пароль:</b> <code>{password}</code>" if password else "")
                        ),
                        parse_mode='HTML',
                    )
                except Exception as ne:
                    logger.warning(f"Failed to notify participant {p_id} about reschedule: {ne}")

            # Re-schedule reminders
            pids = [p['telegram_id'] for p in participants if p.get('telegram_id')]
            if context.job_queue:
                self._clear_meeting_reminder_jobs(context.job_queue, int(meeting_id))
                if pids:
                    self._schedule_meeting_reminders(
                        context.job_queue,
                        meeting_id=int(meeting_id),
                        topic=topic,
                        join_url=join_url,
                        start_time_str=start_time,
                        participant_ids=pids,
                        host_id=meeting.get('host_telegram_id'),
                        start_url=start_url,
                    )

            # Sync Lark card by replacing old message
            if self.lark:
                try:
                    old_msg_id = meeting.get('lark_message_id')
                    if old_msg_id:
                        try:
                            await self.lark.delete_message(old_msg_id)
                        except Exception as de:
                            logger.warning(f"Failed to delete old Lark meeting card: {de}")

                    # Build participant labels with notes
                    participants_list = []
                    for p in participants:
                        p_id = p.get('telegram_id')
                        note = await self.db.get_staff_note(p_id) if p_id else ""
                        participants_list.append({
                            'telegram_id': p_id,
                            'first_name': p.get('first_name'),
                            'last_name': p.get('last_name'),
                            'username': p.get('username'),
                            'note': note,
                        })

                    host_id = meeting.get('host_telegram_id')
                    host_note = await self.db.get_staff_note(host_id) if host_id else ""
                    host_name = self._format_person_label(
                        first_name=meeting.get('host_name'),
                        username=None,
                        note=host_note or None,
                    )

                    end_time_label = (
                        datetime.fromisoformat(start_time).astimezone(zoneinfo.ZoneInfo("Europe/Moscow"))
                        + timedelta(minutes=duration)
                    ).strftime('%H:%M') + " МСК"
                    meeting_projects = await self.db.get_projects_for_meeting_by_meeting_id(int(meeting_id))
                    project_name = meeting_projects[0]['name'] if meeting_projects else None

                    result = await self.lark.send_meeting_card(
                        topic=topic,
                        duration=duration,
                        join_url=join_url,
                        start_url=start_url,
                        host_name=host_name,
                        start_time=date_label,
                        end_time=end_time_label,
                        participants=participants_list if participants_list else None,
                        host_note=host_note or None,
                        password=password or None,
                        project_name=project_name,
                        card_title="🔄 Zoom-встреча перенесена",
                    )
                    new_lark_msg_id = result.get("data", {}).get("message_id")
                    if new_lark_msg_id:
                        await self.db.update_meeting_lark_message_id(int(meeting_id), new_lark_msg_id)
                except Exception as le:
                    logger.error(f"Failed to sync rescheduled meeting card in Lark: {le}")

            context.user_data['_last_join_url'] = join_url
            context.user_data['_last_topic'] = topic
            context.user_data['_last_date_label'] = date_label
            context.user_data['_last_duration_label'] = duration_label
            context.user_data['_last_password'] = password

            text = (
                "✅ <b>Встреча перенесена</b>\n\n"
                f"📌 <b>Тема:</b> {topic}\n"
                f"📅 <b>Новое время:</b> {date_label}\n"
                f"⏱ <b>Длительность:</b> {duration_label}\n"
            )
            if password:
                text += f"🔑 <b>Пароль:</b> <code>{password}</code>\n"

            keyboard = [
                [InlineKeyboardButton("🎬 Начать встречу (Хост)", url=start_url)],
                [InlineKeyboardButton("📨 Пригласить участников", callback_data="zoom_share_invite")],
                [InlineKeyboardButton("🕒 Перенести время", callback_data=f"zoom_reschedule_{meeting_id}")],
                [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Failed to reschedule meeting {meeting_id}: {e}", exc_info=True)
            await query.edit_message_text(
                f"❌ Ошибка при переносе:\n<code>{str(e)[:200]}</code>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")]]),
                parse_mode='HTML',
            )
        finally:
            for key in ['zoom_mode', 'zoom_edit_meeting_id', 'zoom_start_time', 'zoom_date']:
                context.user_data.pop(key, None)

        return STAFF_MENU

    # --- Create meeting + send invitations + schedule reminders ---

    def _format_person_label(
        self,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
        note: str | None = None,
    ) -> str:
        """Return display label with priority: note > username > first/last."""
        if note and str(note).strip():
            return str(note).strip()
        if username and str(username).strip():
            return f"@{str(username).strip().lstrip('@')}"
        full_name = f"{(first_name or '').strip()} {(last_name or '').strip()}".strip()
        if full_name:
            return full_name
        return (first_name or "Участник").strip() if first_name else "Участник"

    def _format_date_label(self, start_time_iso: str | None) -> str:
        if not start_time_iso:
            return "Сейчас"
        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        dt = datetime.fromisoformat(start_time_iso).astimezone(tz)
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        month_names = ["", "янв", "фев", "мар", "апр", "мая", "июн",
                       "июл", "авг", "сен", "окт", "ноя", "дек"]
        return f"{day_names[dt.weekday()]}, {dt.day} {month_names[dt.month]} в {dt.strftime('%H:%M')} МСК"

    def _clear_meeting_reminder_jobs(self, job_queue, meeting_id: int):
        if not job_queue:
            return
        for delta in (3600, 300):  # 1h, 5m
            name = f"remind_{meeting_id}_{delta}"
            for job in job_queue.get_jobs_by_name(name):
                job.schedule_removal()

    def _duration_label(self, duration: int) -> str:
        if duration >= 60:
            h, m = divmod(duration, 60)
            return f"{h} ч" + (f" {m} мин" if m else "")
        return f"{duration} мин"

    @staticmethod
    def _make_gcal_url(topic: str, start_time_iso: str | None, duration_min: int,
                       zoom_url: str, is_host: bool = False) -> str | None:
        """Build a Google Calendar quick-add URL for the meeting."""
        if not start_time_iso:
            return None
        try:
            dt = datetime.fromisoformat(start_time_iso).astimezone(timezone.utc)
            start = dt.strftime('%Y%m%dT%H%M%SZ')
            end = (dt + timedelta(minutes=duration_min)).strftime('%Y%m%dT%H%M%SZ')
            if is_host:
                details = f"Ссылка хоста (только для вас): {zoom_url}"
            else:
                details = f"Ссылка для подключения: {zoom_url}"
            return (
                "https://calendar.google.com/calendar/render?action=TEMPLATE"
                f"&text={quote(topic)}"
                f"&dates={start}/{end}"
                f"&details={quote(details)}"
                f"&location={quote(zoom_url)}"
            )
        except Exception:
            return None

    async def _create_meeting_and_invite(self, query, context):
        topic = context.user_data.get('zoom_topic', 'Встреча')
        duration = context.user_data.get('zoom_duration', 60)
        start_time = context.user_data.get('zoom_start_time')
        participants = context.user_data.get('zoom_participants', set())
        project_id = context.user_data.get('zoom_project_id')
        user = query.from_user

        await query.edit_message_text("⏳ Создаю Zoom-встречу...")

        try:
            meeting = await self.zoom.create_meeting(
                topic=topic,
                duration_minutes=duration,
                start_time=start_time,
            )

            meeting_id = meeting['id']
            join_url = meeting['join_url']
            start_url = meeting['start_url']
            password = meeting.get('password', '')

            await self.db.save_zoom_meeting(
                meeting_id=meeting_id,
                topic=topic,
                duration=duration,
                join_url=join_url,
                start_url=start_url,
                host_telegram_id=user.id,
                host_name=user.first_name,
                start_time=datetime.fromisoformat(start_time) if start_time else None,
            )

            # Link to project if selected
            if project_id:
                try:
                    saved = await self.db.get_meeting_by_zoom_id(meeting_id)
                    if saved:
                        await self.db.add_meeting_to_project(project_id, saved['id'])
                        logger.info(f"Meeting {meeting_id} linked to project {project_id}")
                except Exception as e:
                    logger.error(f"Failed to link meeting to project: {e}")

            duration_label = self._duration_label(duration)
            date_label = self._format_date_label(start_time)

            # Get project name if linked
            project_name = None
            if project_id:
                try:
                    all_projects = await self.db.get_all_projects()
                    proj = next((p for p in all_projects if p['id'] == project_id), None)
                    if proj:
                        project_name = proj['name']
                except Exception:
                    pass

            card_text = (
                "✅ <b>Zoom-встреча создана!</b>\n\n"
                f"📌 <b>Тема:</b> {topic}\n"
                f"⏱ <b>Длительность:</b> {duration_label}\n"
                f"📅 <b>Когда:</b> {date_label}\n"
            )
            if password:
                card_text += f"🔑 <b>Пароль:</b> <code>{password}</code>\n"
            if participants:
                card_text += f"\n👥 <b>Приглашено:</b> {len(participants)} чел.\n"
            if project_name:
                card_text += f"📁 <b>Проект:</b> {project_name}\n"

            context.user_data['_last_join_url'] = join_url
            context.user_data['_last_topic'] = topic
            context.user_data['_last_date_label'] = date_label
            context.user_data['_last_duration_label'] = duration_label
            context.user_data['_last_password'] = password

            gcal_url_host = self._make_gcal_url(topic, start_time, duration, start_url, is_host=True)

            # Meeting card buttons — no navigation buttons so the card stays clean in the feed
            meeting_kb = [
                [InlineKeyboardButton("🎬 Начать встречу (Хост)", url=start_url)],
            ]
            if gcal_url_host:
                meeting_kb.append([InlineKeyboardButton("📅 Добавить в Google Calendar", url=gcal_url_host)])
            meeting_kb += [
                [InlineKeyboardButton("📨 Пригласить участников", callback_data="zoom_share_invite")],
                [InlineKeyboardButton("🕒 Перенести время", callback_data=f"zoom_reschedule_{meeting_id}")],
            ]

            # Send as a NEW message so it stays permanently in the chat feed
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=card_text,
                reply_markup=InlineKeyboardMarkup(meeting_kb),
                parse_mode='HTML',
            )
            # Replace the "creating..." message with a minimal nav message
            await query.edit_message_text(
                "✅ Встреча создана!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📹 Создать ещё", callback_data="staff_create_zoom")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
            )

            # Send Lark card
            if self.lark:
                try:
                    participants_list = []
                    if participants:
                        staff_by_id = {s['telegram_id']: s for s in context.user_data.get('_staff_list', [])}
                        for p_id in participants:
                            staff_user = staff_by_id.get(p_id, {})
                            note = await self.db.get_staff_note(p_id)
                            participants_list.append({
                                'telegram_id': p_id,
                                'first_name': staff_user.get('first_name'),
                                'last_name': staff_user.get('last_name'),
                                'username': staff_user.get('username'),
                                'note': note,
                            })

                    host_note = await self.db.get_staff_note(user.id)
                    host_label = self._format_person_label(
                        first_name=user.first_name,
                        last_name=user.last_name,
                        username=user.username,
                        note=host_note or None,
                    )

                    end_time_label = None
                    if start_time:
                        tz_end = zoneinfo.ZoneInfo("Europe/Moscow")
                        dt_end = (datetime.fromisoformat(start_time).astimezone(tz_end)
                                  + timedelta(minutes=duration))
                        end_time_label = dt_end.strftime('%H:%M') + " МСК"

                    result = await self.lark.send_meeting_card(
                        topic=topic,
                        duration=duration,
                        join_url=join_url,
                        start_url=start_url,
                        host_name=host_label,
                        start_time=date_label if start_time else None,
                        end_time=end_time_label,
                        participants=participants_list if participants_list else None,
                        host_note=host_note or None,
                        password=password or None,
                        project_name=project_name,
                    )
                    lark_msg_id = result.get("data", {}).get("message_id")
                    if lark_msg_id:
                        await self.db.update_meeting_lark_message_id(meeting_id, lark_msg_id)
                    logger.info("Meeting card sent to Lark group")
                except Exception as e:
                    logger.error(f"Failed to send Lark meeting card: {e}")

            # Send invitations to participants
            if participants:
                await self.db.save_meeting_participants(meeting_id, list(participants))
                invite_text = (
                    f"📹 <b>Приглашение на Zoom-встречу</b>\n"
                    f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                    f"📌 <b>Тема:</b> {topic}\n"
                    f"👤 <b>Организатор:</b> {user.first_name}\n"
                    f"🗓 <b>Когда:</b> {date_label}\n"
                    f"⏱ <b>Длительность:</b> {duration_label}\n"
                )
                if password:
                    invite_text += f"🔑 <b>Пароль:</b> <code>{password}</code>\n"
                invite_text += (
                    f"\n💼 <i>{self.config.company_name}</i>\n"
                    f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                    f"Ждём вас на встрече! 👋"
                )

                gcal_url_guest = self._make_gcal_url(topic, start_time, duration, join_url, is_host=False)
                invite_kb_buttons = [
                    [InlineKeyboardButton("🔗 Присоединиться к встрече", url=join_url)],
                ]
                if gcal_url_guest:
                    invite_kb_buttons.append([InlineKeyboardButton("📅 Добавить в Google Calendar", url=gcal_url_guest)])
                invite_kb = InlineKeyboardMarkup(invite_kb_buttons)

                for tid in participants:
                    try:
                        await context.bot.send_message(
                            chat_id=tid,
                            text=invite_text,
                            reply_markup=invite_kb,
                            parse_mode='HTML',
                        )
                    except Exception as e:
                        logger.error(f"Failed to send invite to {tid}: {e}")

            # Schedule reminders for future meetings
            if start_time and participants and context.job_queue:
                self._schedule_meeting_reminders(
                    context.job_queue,
                    meeting_id=meeting_id,
                    topic=topic,
                    join_url=join_url,
                    start_time_str=start_time,
                    participant_ids=list(participants),
                    host_id=user.id,
                    start_url=start_url,
                )

        except Exception as e:
            logger.error(f"Failed to create Zoom meeting: {e}", exc_info=True)
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="staff_create_zoom")],
                [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
            ]
            await query.edit_message_text(
                f"❌ Ошибка при создании встречи:\n<code>{str(e)[:200]}</code>",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML',
            )

        # Cleanup user_data
        for key in ['zoom_topic', 'zoom_duration', 'zoom_start_time', 'zoom_date',
                     'zoom_participants', '_staff_list', '_staff_notes', 'zoom_project_id',
                     'zoom_mode', 'zoom_edit_meeting_id']:
            context.user_data.pop(key, None)

        return STAFF_MENU

    # --- Reminder scheduling ---

    def _schedule_meeting_reminders(self, job_queue, meeting_id, topic, join_url,
                                     start_time_str, participant_ids, host_id,
                                     start_url=None):
        if not job_queue:
            logger.warning(f"Meeting {meeting_id}: job_queue is None, skipping reminder scheduling")
            return
        self._clear_meeting_reminder_jobs(job_queue, meeting_id)
        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        start_dt = datetime.fromisoformat(start_time_str).astimezone(tz)
        now = datetime.now(tz)

        participant_ids = [pid for pid in participant_ids if pid != host_id]

        for delta, label in [(timedelta(hours=1), "1 час"), (timedelta(minutes=5), "5 минут")]:
            remind_at = start_dt - delta
            if remind_at > now:
                job_queue.run_once(
                    self._send_reminder,
                    when=remind_at,
                    data={
                        "topic": topic,
                        "join_url": join_url,
                        "start_url": start_url or join_url,
                        "label": label,
                        "participant_ids": participant_ids,
                        "host_id": host_id,
                        "meeting_id": meeting_id,
                    },
                    name=f"remind_{meeting_id}_{int(delta.total_seconds())}",
                )
                logger.info(f"Reminder scheduled for meeting {meeting_id} at {remind_at} ({label} before)")

    @staticmethod
    async def _send_reminder(context: ContextTypes.DEFAULT_TYPE):
        data = context.job.data
        text = (
            f"⏰ <b>Напоминание!</b>\n\n"
            f"Встреча «<b>{data['topic']}</b>» начнётся через <b>{data['label']}</b>.\n"
        )
        join_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Присоединиться", url=data['join_url'])],
        ])
        host_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Начать встречу (host)", url=data['start_url'])],
        ])

        host_id = data.get('host_id')
        if host_id:
            try:
                await context.bot.send_message(chat_id=host_id, text=text, reply_markup=host_kb, parse_mode='HTML')
            except Exception as e:
                logger.error(f"Failed to send host reminder to {host_id}: {e}")

        for cid in data.get('participant_ids', []):
            try:
                await context.bot.send_message(chat_id=cid, text=text, reply_markup=join_kb, parse_mode='HTML')
            except Exception as e:
                logger.error(f"Failed to send reminder to {cid}: {e}")

    async def reschedule_meeting_reminders(self, application):
        """Re-schedule reminders for upcoming meetings after bot restart."""
        await self.initialize_db()
        meetings = await self.db.get_upcoming_meetings()
        for m in meetings:
            if not m.get('start_time'):
                continue
            participants = await self.db.get_meeting_participants(m['meeting_id'])
            pids = [p['telegram_id'] for p in participants]
            if not pids:
                continue
            self._schedule_meeting_reminders(
                application.job_queue,
                meeting_id=m['meeting_id'],
                topic=m['topic'],
                join_url=m['join_url'],
                start_time_str=m['start_time'].isoformat(),
                participant_ids=pids,
                host_id=m['host_telegram_id'],
                start_url=m.get('start_url'),
            )
        logger.info(f"Re-scheduled reminders for {len(meetings)} upcoming meetings")

    async def staff_menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to staff menu from callback."""
        for key in ['zoom_topic', 'zoom_duration', 'zoom_start_time', 'zoom_date',
                     'zoom_participants', '_staff_list', '_staff_notes',
                     'zoom_project_id', 'zoom_mode', 'zoom_edit_meeting_id']:
            context.user_data.pop(key, None)
        return await self.show_staff_menu(update, context, via_message=False)

    async def zoom_share_invite(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate a shareable invitation text for forwarding to clients."""
        query = update.callback_query

        topic = context.user_data.get('_last_topic', 'Встреча')
        join_url = context.user_data.get('_last_join_url', '')
        date_label = context.user_data.get('_last_date_label', '')
        duration_label = context.user_data.get('_last_duration_label', '')
        password = context.user_data.get('_last_password', '')

        if not join_url:
            await query.answer()
            await query.edit_message_text(
                "⚠️ Данные о встрече не найдены. Создайте новую встречу.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
            )
            return STAFF_MENU

        invite_text = (
            f"📹 Приглашение на видеовстречу\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"📌 Тема: {topic}\n"
            f"🗓 Когда: {date_label}\n"
            f"⏱ Длительность: {duration_label}\n"
        )
        if password:
            invite_text += f"🔑 Пароль: {password}\n"
        invite_text += (
            f"\n🔗 Ссылка для подключения:\n{join_url}\n\n"
            f"💼 {self.config.company_name}\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
            f"Ждём вас на встрече! 👋"
        )

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=invite_text,
        )

        await query.answer("✅ Приглашение отправлено отдельным сообщением", show_alert=True)
        return STAFF_MENU

    # --- Admin: View Staff ---

    async def admin_view_staff(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show list of all staff members."""
        query = update.callback_query
        await query.answer()

        await self.initialize_db()
        staff = await self.db.get_all_staff()

        if not staff:
            await query.edit_message_text(
                "👥 <b>Сотрудники</b>\n\nСписок пуст.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
            )
            return STAFF_MENU

        text = "👥 <b>Сотрудники компании</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        buttons = []
        for s in staff:
            tid = s['telegram_id']
            name = s.get('first_name') or str(tid)
            last = s.get('last_name')
            if last:
                name = f"{name} {last}"
            uname = f" @{s['username']}" if s.get('username') else ""
            role_badge = "🔑" if s.get('role') == 'admin' else "👤"
            note = s.get('note') or ""
            grade_key = s.get('staff_grade')
            specialty_key = s.get('staff_specialty')

            grade_line = ""
            if grade_key and specialty_key:
                grade_info = _get_grade_info(grade_key)
                if grade_info:
                    grade_line = f"   💼 {grade_info['specialty_label']} · {grade_info['label']} · {grade_info['rate']:,} ₽/ч\n"
            elif specialty_key and specialty_key in STAFF_SPECIALTIES:
                grade_line = f"   💼 {STAFF_SPECIALTIES[specialty_key]['label']} · грейд не назначен\n"

            text += f"{role_badge} <b>{name}</b>{uname}\n"
            if grade_line:
                text += grade_line
            if note:
                text += f"   📝 <i>{note}</i>\n"
            text += "\n"

            buttons.append([InlineKeyboardButton(
                f"👤 {name}",
                callback_data=f"admin_profile_{tid}",
            )])

        buttons.append([InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")])

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='HTML',
        )
        return ADMIN_VIEW_STAFF

    # --- Admin: Staff Profile ---

    async def admin_staff_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed profile of a staff member."""
        query = update.callback_query
        await query.answer()

        tid = int(query.data.replace("admin_profile_", ""))
        context.user_data['_profile_target_id'] = tid

        await self.initialize_db()
        staff = await self.db.get_all_staff()
        target = next((s for s in staff if s['telegram_id'] == tid), None)

        if not target:
            await query.edit_message_text("❌ Сотрудник не найден.")
            return ADMIN_VIEW_STAFF

        name = target.get('first_name') or str(tid)
        if target.get('last_name'):
            name += f" {target['last_name']}"
        uname = f"@{target['username']}" if target.get('username') else "—"
        role_badge = "🔑 Администратор" if target.get('role') == 'admin' else "👤 Сотрудник"

        grade_key = target.get('staff_grade')
        specialty_key = target.get('staff_specialty')
        grade_info = _get_grade_info(grade_key) if grade_key else None

        if grade_info:
            spec_line = f"{grade_info['specialty_label']}"
            grade_line = grade_info['label']
            is_transition = grade_info.get('transition', False)
            if is_transition:
                grade_line += " <i>(переходный)</i>"
            rate_line = f"{grade_info['rate']:,} ₽/ч"
        elif specialty_key and specialty_key in STAFF_SPECIALTIES:
            spec_line = STAFF_SPECIALTIES[specialty_key]['label']
            grade_line = "<i>не назначен</i>"
            rate_line = "—"
        else:
            spec_line = "<i>не назначена</i>"
            grade_line = "<i>не назначен</i>"
            rate_line = "—"

        note = target.get('note') or "—"

        text = (
            f"👤 <b>{name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 {uname}\n"
            f"🏷 {role_badge}\n\n"
            f"💼 <b>Специализация:</b> {spec_line}\n"
            f"📊 <b>Грейд:</b> {grade_line}\n"
            f"💰 <b>Ставка:</b> {rate_line}\n\n"
            f"📝 <b>Заметка:</b> <i>{note}</i>"
        )

        buttons = [
            [InlineKeyboardButton("💼 Специализация / Грейд", callback_data=f"admin_specialty_{tid}")],
            [InlineKeyboardButton("📝 Редактировать заметку", callback_data=f"admin_note_{tid}")],
            [InlineKeyboardButton("◀️ Назад к списку", callback_data="admin_view_staff")],
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='HTML',
        )
        return ADMIN_STAFF_PROFILE

    async def admin_note_select(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin selected a staff member to add/edit note."""
        query = update.callback_query
        await query.answer()

        tid = int(query.data.replace("admin_note_", ""))
        context.user_data['_note_target_id'] = tid

        await self.initialize_db()
        staff = await self.db.get_all_staff()
        target = next((s for s in staff if s['telegram_id'] == tid), None)

        name = "Сотрудник"
        if target:
            name = target.get('first_name') or str(tid)
            if target.get('last_name'):
                name += f" {target['last_name']}"

        current_note = await self.db.get_staff_note(tid)

        text = f"📝 <b>Заметка о сотруднике</b>\n\n👤 {name}\n\n"
        if current_note:
            text += f"Текущая заметка:\n<i>{current_note}</i>\n\n"
        else:
            text += "Заметка пока не добавлена.\n\n"
        text += "Отправьте текст новой заметки:"

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Удалить заметку", callback_data="admin_note_clear")],
                [InlineKeyboardButton("◀️ Назад к профилю", callback_data=f"admin_profile_{tid}")],
            ]),
            parse_mode='HTML',
        )
        return ADMIN_EDIT_NOTE

    async def admin_note_text_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin sent text for a staff note."""
        tid = context.user_data.get('_note_target_id')
        if not tid:
            return await self.show_staff_menu(update, context, via_message=True)

        note = update.message.text.strip()[:500]
        await self.db.save_staff_note(tid, note, update.effective_user.id)

        await update.message.reply_text(
            "✅ Заметка сохранена.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад к профилю", callback_data=f"admin_profile_{tid}")],
                [InlineKeyboardButton("👥 Сотрудники", callback_data="admin_view_staff")],
            ]),
            parse_mode='HTML',
        )
        context.user_data.pop('_note_target_id', None)
        return ADMIN_STAFF_PROFILE

    async def admin_note_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clear note for selected staff member."""
        query = update.callback_query
        await query.answer()

        tid = context.user_data.get('_note_target_id')
        if tid:
            await self.db.save_staff_note(tid, "", update.effective_user.id)

        context.user_data.pop('_note_target_id', None)

        back_buttons = []
        if tid:
            back_buttons.append([InlineKeyboardButton("◀️ Назад к профилю", callback_data=f"admin_profile_{tid}")])
        back_buttons.append([InlineKeyboardButton("👥 Сотрудники", callback_data="admin_view_staff")])

        await query.edit_message_text(
            "🗑 Заметка удалена.",
            reply_markup=InlineKeyboardMarkup(back_buttons),
            parse_mode='HTML',
        )
        return ADMIN_STAFF_PROFILE if tid else ADMIN_VIEW_STAFF

    # --- Admin: Set Specialty & Grade ---

    async def admin_set_specialty(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show specialty selection for a staff member."""
        query = update.callback_query
        await query.answer()

        tid = int(query.data.replace("admin_specialty_", ""))
        context.user_data['_profile_target_id'] = tid

        await self.initialize_db()
        staff = await self.db.get_all_staff()
        target = next((s for s in staff if s['telegram_id'] == tid), None)
        name = (target.get('first_name') or str(tid)) if target else str(tid)

        current_spec = (target.get('staff_specialty') or '') if target else ''
        current_grade = (target.get('staff_grade') or '') if target else ''
        grade_info = _get_grade_info(current_grade) if current_grade else None

        text = (
            f"💼 <b>Специализация: {name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        if grade_info:
            text += f"Текущий грейд: {grade_info['specialty_label']} · {grade_info['label']} · {grade_info['rate']:,} ₽/ч\n\n"
        elif current_spec and current_spec in STAFF_SPECIALTIES:
            text += f"Текущая специализация: {STAFF_SPECIALTIES[current_spec]['label']}, грейд не назначен\n\n"
        else:
            text += "Специализация ещё не назначена.\n\n"
        text += "Выберите специализацию:"

        buttons = []
        for spec_key, spec in STAFF_SPECIALTIES.items():
            mark = " ✅" if spec_key == current_spec else ""
            buttons.append([InlineKeyboardButton(
                f"{spec['label']}{mark}",
                callback_data=f"admin_spec_{tid}_{spec_key}",
            )])
        buttons.append([InlineKeyboardButton("◀️ Назад к профилю", callback_data=f"admin_profile_{tid}")])

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
        return ADMIN_SET_SPECIALTY

    async def admin_set_grade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show grade selection for chosen specialty."""
        query = update.callback_query
        await query.answer()

        parts = query.data.replace("admin_spec_", "").split("_", 1)
        tid = int(parts[0])
        spec_key = parts[1]
        context.user_data['_profile_target_id'] = tid
        context.user_data['_grade_specialty'] = spec_key

        if spec_key not in STAFF_SPECIALTIES:
            await query.answer("Неизвестная специализация", show_alert=True)
            return ADMIN_SET_SPECIALTY

        spec = STAFF_SPECIALTIES[spec_key]

        await self.initialize_db()
        staff = await self.db.get_all_staff()
        target = next((s for s in staff if s['telegram_id'] == tid), None)
        current_grade = (target.get('staff_grade') or '') if target else ''
        name = (target.get('first_name') or str(tid)) if target else str(tid)

        text = (
            f"📊 <b>Грейд: {name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Специализация: {spec['label']}\n\n"
            f"Выберите грейд:"
        )

        buttons = []
        for grade_key, grade in spec['grades'].items():
            mark = " ✅" if grade_key == current_grade else ""
            transition_mark = " ⬆️" if grade.get('transition') else ""
            label = f"{grade['label']}{transition_mark} · {grade['rate']:,} ₽/ч{mark}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"admin_grade_save_{tid}_{grade_key}")])
        buttons.append([InlineKeyboardButton("◀️ Назад к специализации", callback_data=f"admin_specialty_{tid}")])

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
        return ADMIN_SET_GRADE

    async def admin_grade_save(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Save selected grade and return to staff profile."""
        query = update.callback_query
        await query.answer()

        data = query.data.replace("admin_grade_save_", "")
        sep = data.index("_")
        tid = int(data[:sep])
        grade_key = data[sep + 1:]

        grade_info = _get_grade_info(grade_key)
        if not grade_info:
            await query.answer("Неизвестный грейд", show_alert=True)
            return ADMIN_SET_GRADE

        spec_key = grade_info['specialty_key']
        await self.initialize_db()
        await self.db.update_staff_grade_info(tid, spec_key, grade_key)

        await query.answer(f"✅ Грейд назначен: {grade_info['label']}", show_alert=False)

        context.user_data['_profile_target_id'] = tid
        query.data = f"admin_profile_{tid}"
        return await self.admin_staff_profile(update, context)

    async def admin_create_invite(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate a reusable staff invite deep-link."""
        import uuid
        query = update.callback_query
        await query.answer()

        user = update.effective_user
        token = uuid.uuid4().hex[:16]
        await self.db.save_invite_link(token, user.id)

        bot_me = await context.bot.get_me()
        invite_url = f"https://t.me/{bot_me.username}?start=invite_{token}"

        text = (
            "<b>🔗 Ссылка для приглашения сотрудника</b>\n\n"
            "Отправьте эту ссылку новому сотруднику.\n"
            "После перехода по ссылке его роль автоматически\n"
            "изменится на <b>staff</b>.\n\n"
            f"<code>{invite_url}</code>\n\n"
            "<i>Ссылка многоразовая — можно отправлять нескольким людям.</i>"
        )
        keyboard = [
            [InlineKeyboardButton("◀️  Меню", callback_data="staff_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        except Exception:
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return STAFF_MENU

    # --- Admin: Report Menu (Kimai) ---

    async def admin_report_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show report type selection: employee report or client report."""
        query = update.callback_query
        await query.answer()

        if not self.kimai:
            await query.edit_message_text(
                "❌ Kimai не настроен. Добавьте KIMAI_URL и KIMAI_API_TOKEN в .env",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
            )
            return STAFF_MENU

        text = (
            "📊 <b>Создать отчёт</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Выберите тип отчёта:"
        )
        keyboard = [
            [InlineKeyboardButton("👥  Отчёт по сотрудникам", callback_data="admin_team_report")],
            [InlineKeyboardButton("📄  Отчёт для клиента", callback_data="admin_client_report")],
            [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return ADMIN_REPORT_MENU

    # --- Employee Report (Excel) ---

    async def admin_team_report_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show prompt asking for date range for employee Excel report."""
        query = update.callback_query
        await query.answer()

        text = (
            "👥 <b>Отчёт по сотрудникам</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Введите период отчёта в формате:\n"
            "<code>ДД.ММ.ГГГГ - ДД.ММ.ГГГГ</code>\n\n"
            "Например: <code>1.02.2026 - 15.02.2026</code>"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="admin_report_menu")],
            ]),
            parse_mode='HTML',
        )
        return ADMIN_TEAM_REPORT_DATES

    async def admin_team_report_dates_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Parse dates, fetch Kimai data, generate Excel, send file."""
        raw = update.message.text.strip()

        try:
            parts = [p.strip() for p in raw.split("-", 1)]
            if len(parts) != 2:
                raise ValueError("expected 2 dates")
            begin_dt = datetime.strptime(parts[0].strip(), "%d.%m.%Y")
            end_dt = datetime.strptime(parts[1].strip(), "%d.%m.%Y")
            if begin_dt > end_dt:
                begin_dt, end_dt = end_dt, begin_dt
        except (ValueError, IndexError):
            await update.message.reply_text(
                "⚠️ Неверный формат дат.\n\n"
                "Используйте: <code>ДД.ММ.ГГГГ - ДД.ММ.ГГГГ</code>\n"
                "Например: <code>1.02.2026 - 15.02.2026</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="admin_report_menu")],
                ]),
                parse_mode='HTML',
            )
            return ADMIN_TEAM_REPORT_DATES

        begin_api = begin_dt.strftime("%Y-%m-%dT00:00:00")
        end_api = end_dt.strftime("%Y-%m-%dT23:59:59")
        begin_label = begin_dt.strftime("%d.%m.%Y")
        end_label = end_dt.strftime("%d.%m.%Y")

        wait_msg = await update.message.reply_text(
            f"⏳ Формирую отчёт за {begin_label} — {end_label}…\nЭто может занять некоторое время.",
            parse_mode='HTML',
        )

        try:
            data = await self.kimai.build_team_report_data(begin_api, end_api)
            pdf_bytes = generate_team_report_excel(
                teams=data["teams"],
                projects_map=data["projects_map"],
                report_by_team=data["report_by_team"],
                begin_label=begin_label,
                end_label=end_label,
            )
            import io
            doc = io.BytesIO(pdf_bytes)
            doc.name = f"Отчёт_по_сотрудникам_{begin_label}-{end_label}.pdf"

            await context.bot.send_document(
                chat_id=update.effective_user.id,
                document=doc,
                caption=f"📊 Отчёт по сотрудникам за {begin_label} — {end_label}",
            )
            try:
                await wait_msg.delete()
            except Exception:
                pass

            await update.message.reply_text(
                "✅ Отчёт сформирован и отправлен.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 Ещё один отчёт", callback_data="admin_report_menu")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
            )
        except Exception as e:
            logger.error(f"Team report generation failed: {e}", exc_info=True)
            try:
                await wait_msg.delete()
            except Exception:
                pass
            await update.message.reply_text(
                f"❌ Ошибка при формировании отчёта:\n<code>{str(e)[:300]}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data="admin_team_report")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
            )
        return STAFF_MENU

    # --- Client Report (PDF) ---

    async def admin_client_report_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fetch customers from Kimai and show selection buttons."""
        query = update.callback_query
        await query.answer()

        try:
            customers = await self.kimai.get_customers()
        except Exception as e:
            logger.error(f"Failed to fetch Kimai customers: {e}", exc_info=True)
            await query.edit_message_text(
                f"❌ Не удалось загрузить список клиентов:\n<code>{str(e)[:200]}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="admin_report_menu")],
                ]),
                parse_mode='HTML',
            )
            return ADMIN_REPORT_MENU

        if not customers:
            await query.edit_message_text(
                "📄 <b>Отчёт для клиента</b>\n\nСписок клиентов пуст.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="admin_report_menu")],
                ]),
                parse_mode='HTML',
            )
            return ADMIN_REPORT_MENU

        text = (
            "📄 <b>Отчёт для клиента</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Выберите заказчика:"
        )
        keyboard = []
        for c in customers:
            if c.get("visible", True):
                keyboard.append([InlineKeyboardButton(
                    c["name"], callback_data=f"client_pick_{c['id']}",
                )])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_report_menu")])

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return ADMIN_CLIENT_SELECT_CUSTOMER

    async def admin_client_select_customer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User picked a customer; fetch their projects and show toggleable selection."""
        query = update.callback_query
        await query.answer()

        customer_id = int(query.data.replace("client_pick_", ""))
        context.user_data['_report_customer_id'] = customer_id

        try:
            customer = await self.kimai.get_customer(customer_id)
            context.user_data['_report_customer_name'] = customer.get("name", f"Клиент {customer_id}")

            projects = await self.kimai.get_projects()
            customer_projects = [p for p in projects if p.get("customer") == customer_id]
        except Exception as e:
            logger.error(f"Failed to fetch projects for customer {customer_id}: {e}", exc_info=True)
            await query.edit_message_text(
                f"❌ Ошибка загрузки проектов:\n<code>{str(e)[:200]}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="admin_client_report")],
                ]),
                parse_mode='HTML',
            )
            return ADMIN_CLIENT_SELECT_CUSTOMER

        if not customer_projects:
            await query.edit_message_text(
                f"📄 У клиента <b>{context.user_data['_report_customer_name']}</b> нет проектов.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="admin_client_report")],
                ]),
                parse_mode='HTML',
            )
            return ADMIN_CLIENT_SELECT_CUSTOMER

        context.user_data['_report_available_projects'] = {
            p["id"]: p["name"] for p in customer_projects
        }
        context.user_data['_report_selected_projects'] = set()

        return await self._show_project_selection(query, context)

    async def _show_project_selection(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Render the project multi-select toggle screen."""
        available = context.user_data.get('_report_available_projects', {})
        selected = context.user_data.get('_report_selected_projects', set())
        customer_name = context.user_data.get('_report_customer_name', 'Клиент')

        text = (
            f"📄 <b>Клиент: {customer_name}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Выберите проекты для отчёта:\n"
            "<i>(нажмите чтобы выбрать/убрать)</i>"
        )
        keyboard = []
        for pid, pname in sorted(available.items(), key=lambda x: x[1]):
            check = "✅" if pid in selected else "◻️"
            keyboard.append([InlineKeyboardButton(
                f"{check}  {pname}", callback_data=f"client_proj_toggle_{pid}",
            )])

        if selected:
            keyboard.append([InlineKeyboardButton(
                f"✔️  Подтвердить ({len(selected)} шт.)", callback_data="client_proj_confirm",
            )])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_client_report")])

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return ADMIN_CLIENT_SELECT_PROJECTS

    async def admin_client_toggle_project(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle a project in the selection."""
        query = update.callback_query
        await query.answer()

        pid = int(query.data.replace("client_proj_toggle_", ""))
        selected = context.user_data.get('_report_selected_projects', set())
        if pid in selected:
            selected.discard(pid)
        else:
            selected.add(pid)
        context.user_data['_report_selected_projects'] = selected

        return await self._show_project_selection(query, context)

    async def admin_client_confirm_projects(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Projects confirmed — ask for date range."""
        query = update.callback_query
        await query.answer()

        selected = context.user_data.get('_report_selected_projects', set())
        if not selected:
            return await self._show_project_selection(query, context)

        available = context.user_data.get('_report_available_projects', {})
        names = ", ".join(available.get(pid, str(pid)) for pid in sorted(selected))

        text = (
            f"📄 <b>Проекты:</b> {names}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Введите период отчёта в формате:\n"
            "<code>ДД.ММ.ГГГГ - ДД.ММ.ГГГГ</code>\n\n"
            "Например: <code>1.02.2026 - 15.02.2026</code>"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад к проектам", callback_data="client_proj_back")],
            ]),
            parse_mode='HTML',
        )
        return ADMIN_CLIENT_REPORT_DATES

    async def admin_client_report_dates_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Parse dates, fetch Kimai data, generate PDF, send file."""
        raw = update.message.text.strip()

        try:
            parts = [p.strip() for p in raw.split("-", 1)]
            if len(parts) != 2:
                raise ValueError("expected 2 dates")
            begin_dt = datetime.strptime(parts[0].strip(), "%d.%m.%Y")
            end_dt = datetime.strptime(parts[1].strip(), "%d.%m.%Y")
            if begin_dt > end_dt:
                begin_dt, end_dt = end_dt, begin_dt
        except (ValueError, IndexError):
            await update.message.reply_text(
                "⚠️ Неверный формат дат.\n\n"
                "Используйте: <code>ДД.ММ.ГГГГ - ДД.ММ.ГГГГ</code>\n"
                "Например: <code>1.02.2026 - 15.02.2026</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="admin_report_menu")],
                ]),
                parse_mode='HTML',
            )
            return ADMIN_CLIENT_REPORT_DATES

        begin_api = begin_dt.strftime("%Y-%m-%dT00:00:00")
        end_api = end_dt.strftime("%Y-%m-%dT23:59:59")
        begin_label = begin_dt.strftime("%d.%m.%Y")
        end_label = end_dt.strftime("%d.%m.%Y")

        selected_projects = list(context.user_data.get('_report_selected_projects', set()))
        customer_name = context.user_data.get('_report_customer_name', 'Клиент')

        wait_msg = await update.message.reply_text(
            f"⏳ Формирую PDF-отчёт за {begin_label} — {end_label}…\n"
            "Это может занять некоторое время.",
            parse_mode='HTML',
        )

        try:
            data = await self.kimai.build_client_report_data(selected_projects, begin_api, end_api)

            pdf_bytes = generate_client_report_pdf(
                customer_name=customer_name,
                projects_map=data["projects_map"],
                report_by_project=data["report_by_project"],
                begin_label=begin_label,
                end_label=end_label,
                company_name=self.config.company_name or "НейроСофт",
            )

            import io
            doc = io.BytesIO(pdf_bytes)
            doc.name = f"Отчёт_{customer_name}_{begin_label}-{end_label}.pdf"

            await context.bot.send_document(
                chat_id=update.effective_user.id,
                document=doc,
                caption=f"📄 Отчёт для {customer_name} за {begin_label} — {end_label}",
            )
            try:
                await wait_msg.delete()
            except Exception:
                pass

            await update.message.reply_text(
                "✅ PDF-отчёт сформирован и отправлен.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 Ещё один отчёт", callback_data="admin_report_menu")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
            )
        except Exception as e:
            logger.error(f"Client PDF report generation failed: {e}", exc_info=True)
            try:
                await wait_msg.delete()
            except Exception:
                pass
            await update.message.reply_text(
                f"❌ Ошибка при формировании отчёта:\n<code>{str(e)[:300]}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data="admin_report_menu")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
            )
        finally:
            for key in ['_report_customer_id', '_report_customer_name',
                         '_report_available_projects', '_report_selected_projects']:
                context.user_data.pop(key, None)

        return STAFF_MENU

    # ─── Commercial Proposal (KP) handlers ───

    async def admin_cp_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Step 1: Choose MVP or Full calculation."""
        query = update.callback_query
        await query.answer()

        context.user_data['_cp'] = {}

        text = (
            "📄 <b>Коммерческое предложение</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Выберите тип расчёта:"
        )
        keyboard = [
            [InlineKeyboardButton("🚀 MVP (минимальный продукт)", callback_data="cp_type_mvp")],
            [InlineKeyboardButton("📦 Полноценный расчёт", callback_data="cp_type_full")],
            [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if query.message and query.message.photo:
            await query.message.delete()
            await query.message.chat.send_message(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        return CP_TYPE

    async def admin_cp_type_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Step 2: Type selected, ask about budget."""
        query = update.callback_query
        await query.answer()

        cp_type = "mvp" if query.data == "cp_type_mvp" else "full"
        context.user_data['_cp']['type'] = cp_type

        type_label = "MVP" if cp_type == "mvp" else "Полноценный"
        text = (
            f"📄 <b>Коммерческое предложение</b>\n"
            f"Тип: <b>{type_label}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Нужно ли подогнать под определённую сумму?"
        )
        keyboard = [
            [InlineKeyboardButton("💰 Да, есть бюджет", callback_data="cp_budget_yes")],
            [InlineKeyboardButton("📊 Нет, считать без ограничений", callback_data="cp_budget_no")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_cp_start")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return CP_BUDGET

    async def admin_cp_budget_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle budget yes/no choice."""
        query = update.callback_query
        await query.answer()

        if query.data == "cp_budget_yes":
            text = (
                "📄 <b>Коммерческое предложение</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Введите максимальный бюджет.\n"
                "Укажите сумму с валютой, например:\n"
                "<code>50000$</code> или <code>5000000₽</code>"
            )
            keyboard = [
                [InlineKeyboardButton("◀️ Назад", callback_data="cp_back_to_budget")],
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return CP_BUDGET_AMOUNT
        else:
            context.user_data['_cp']['budget'] = None
            context.user_data['_cp']['budget_currency'] = None
            return await self._cp_ask_design(query, context)

    async def admin_cp_budget_amount_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Parse budget amount from text message."""
        import re
        text = update.message.text.strip()

        match = re.search(r'([\d\s,.]+)\s*(\$|₽|руб|usd|rub)?', text, re.IGNORECASE)
        if not match:
            await update.message.reply_text(
                "❌ Не удалось распознать сумму. Попробуйте ещё раз.\n"
                "Пример: <code>50000$</code> или <code>5000000₽</code>",
                parse_mode='HTML',
            )
            return CP_BUDGET_AMOUNT

        amount_str = match.group(1).replace(" ", "").replace(",", ".")
        try:
            amount = float(amount_str)
        except ValueError:
            await update.message.reply_text(
                "❌ Не удалось распознать число. Попробуйте ещё раз.",
                parse_mode='HTML',
            )
            return CP_BUDGET_AMOUNT

        currency_raw = (match.group(2) or "").lower()
        if currency_raw in ("₽", "руб", "rub"):
            budget_currency = "₽"
        else:
            budget_currency = "$"

        context.user_data['_cp']['budget'] = amount
        context.user_data['_cp']['budget_currency'] = budget_currency

        text = (
            f"✅ Бюджет: {amount:,.0f} {budget_currency}\n\n"
        )
        await update.message.reply_text(text, parse_mode='HTML')
        return await self._cp_ask_design_msg(update, context)

    async def _cp_ask_design(self, query, context):
        """Ask about design needs (from callback query)."""
        text = (
            "📄 <b>Коммерческое предложение</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Что нужно по дизайну?"
        )
        keyboard = [
            [InlineKeyboardButton("🎨 Полный дизайн (UX/UI)", callback_data="cp_design_full")],
            [InlineKeyboardButton("📐 Только вайрфреймы", callback_data="cp_design_wireframes")],
            [InlineKeyboardButton("🚫 Дизайн не нужен", callback_data="cp_design_none")],
            [InlineKeyboardButton("◀️ Назад", callback_data="cp_back_to_budget")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return CP_DESIGN

    async def _cp_ask_design_msg(self, update, context):
        """Ask about design needs (from message context)."""
        text = (
            "📄 <b>Коммерческое предложение</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Что нужно по дизайну?"
        )
        keyboard = [
            [InlineKeyboardButton("🎨 Полный дизайн (UX/UI)", callback_data="cp_design_full")],
            [InlineKeyboardButton("📐 Только вайрфреймы", callback_data="cp_design_wireframes")],
            [InlineKeyboardButton("🚫 Дизайн не нужен", callback_data="cp_design_none")],
            [InlineKeyboardButton("◀️ Назад", callback_data="cp_back_to_budget")],
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return CP_DESIGN

    async def admin_cp_design_selected(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle design choice, ask for hourly rate."""
        query = update.callback_query
        await query.answer()

        design_map = {
            "cp_design_full": "full_design",
            "cp_design_wireframes": "wireframes",
            "cp_design_none": "no_design",
        }
        context.user_data['_cp']['design'] = design_map.get(query.data, "full_design")

        text = (
            "📄 <b>Коммерческое предложение</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Укажите стоимость часа работы.\n"
            "Если сумма в рублях — расчёт будет в ₽,\n"
            "если в долларах — в $.\n\n"
            "Примеры: <code>35$</code> или <code>3000₽</code>"
        )
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="cp_back_to_design")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return CP_HOURLY_RATE

    async def admin_cp_hourly_rate_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Parse hourly rate from text."""
        import re
        text = update.message.text.strip()

        match = re.search(r'([\d\s,.]+)\s*(\$|₽|руб|usd|rub)?', text, re.IGNORECASE)
        if not match:
            await update.message.reply_text(
                "❌ Не удалось распознать ставку. Попробуйте ещё раз.\n"
                "Пример: <code>35$</code> или <code>3000₽</code>",
                parse_mode='HTML',
            )
            return CP_HOURLY_RATE

        amount_str = match.group(1).replace(" ", "").replace(",", ".")
        try:
            rate = float(amount_str)
        except ValueError:
            await update.message.reply_text("❌ Не удалось распознать число.", parse_mode='HTML')
            return CP_HOURLY_RATE

        if rate <= 0:
            await update.message.reply_text("❌ Ставка должна быть больше 0.", parse_mode='HTML')
            return CP_HOURLY_RATE

        currency_raw = (match.group(2) or "").lower()
        if currency_raw in ("₽", "руб", "rub"):
            currency = "₽"
        else:
            currency = "$"

        context.user_data['_cp']['hourly_rate'] = rate
        context.user_data['_cp']['currency'] = currency

        text = (
            f"✅ Ставка: {rate:,.0f} {currency}/час\n\n"
            "📄 <b>Название компании клиента</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Введите название компании клиента (для титульной страницы).\n"
            "Или нажмите <b>Пропустить</b>."
        )
        keyboard = [
            [InlineKeyboardButton("⏭ Пропустить", callback_data="cp_client_skip")],
            [InlineKeyboardButton("◀️ Назад", callback_data="cp_back_to_rate")],
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return CP_CLIENT_NAME

    async def admin_cp_client_name_received(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle client name text input."""
        client_name = update.message.text.strip()
        context.user_data['_cp']['client_name'] = client_name
        return await self._cp_ask_description_msg(update, context)

    async def admin_cp_client_skip(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Skip client name."""
        query = update.callback_query
        await query.answer()
        context.user_data['_cp']['client_name'] = ""
        return await self._cp_ask_description(query, context)

    async def _cp_ask_description(self, query, context):
        """Ask for project description (callback query)."""
        text = (
            "📄 <b>Описание проекта / ТЗ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Отправьте описание проекта или техническое задание.\n\n"
            "Вы можете:\n"
            "• Написать текст прямо сюда\n"
            "• 🎙️ <b>Записать голосовое сообщение</b> — AI расшифрует\n"
            "• Загрузить файл (PDF, DOC, DOCX, TXT)\n"
            "• Отправить ссылку на Google Docs\n"
            "• Отправить несколько сообщений\n\n"
            "Когда закончите — нажмите <b>Сделать коммерческое</b>."
        )
        keyboard = [
            [InlineKeyboardButton("✅ Сделать коммерческое", callback_data="cp_generate")],
            [InlineKeyboardButton("◀️ Назад", callback_data="cp_back_to_client")],
        ]
        context.user_data['_cp']['descriptions'] = []
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return CP_DESCRIPTION

    async def _cp_ask_description_msg(self, update, context):
        """Ask for project description (message context)."""
        text = (
            "📄 <b>Описание проекта / ТЗ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Отправьте описание проекта или техническое задание.\n\n"
            "Вы можете:\n"
            "• Написать текст прямо сюда\n"
            "• 🎙️ <b>Записать голосовое сообщение</b> — AI расшифрует\n"
            "• Загрузить файл (PDF, DOC, DOCX, TXT)\n"
            "• Отправить ссылку на Google Docs\n"
            "• Отправить несколько сообщений\n\n"
            "Когда закончите — нажмите <b>Сделать коммерческое</b>."
        )
        keyboard = [
            [InlineKeyboardButton("✅ Сделать коммерческое", callback_data="cp_generate")],
            [InlineKeyboardButton("◀️ Назад", callback_data="cp_back_to_client")],
        ]
        context.user_data['_cp']['descriptions'] = []
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return CP_DESCRIPTION

    async def admin_cp_description_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Accumulate text messages for project description."""
        text = update.message.text.strip()
        if not text:
            return CP_DESCRIPTION

        if context.user_data.pop('_cp_voice_editing', False):
            context.user_data.pop('_cp_voice_text', None)
            label = "✅ Отредактированный текст принят"
        else:
            label = "✅ Принято"

        descs = context.user_data.get('_cp', {}).get('descriptions', [])
        descs.append(text)
        context.user_data['_cp']['descriptions'] = descs

        count = len(descs)
        await update.message.reply_text(
            f"{label} ({count} фрагмент{'ов' if count > 1 else ''}). "
            "Можете отправить ещё или нажмите <b>Сделать коммерческое</b>.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Сделать коммерческое", callback_data="cp_generate")],
                [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
            ]),
            parse_mode='HTML',
        )
        return CP_DESCRIPTION

    async def admin_cp_description_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle uploaded files (PDF, DOC, DOCX, TXT)."""
        document = update.message.document
        if not document:
            return CP_DESCRIPTION

        file_name = (document.file_name or "").lower()
        file_size = document.file_size or 0

        if file_size > 20 * 1024 * 1024:
            await update.message.reply_text("❌ Файл слишком большой (макс. 20 МБ).")
            return CP_DESCRIPTION

        supported = file_name.endswith(('.pdf', '.doc', '.docx', '.txt', '.md', '.rtf'))
        if not supported:
            await update.message.reply_text(
                "❌ Неподдерживаемый формат файла.\n"
                "Поддерживаются: PDF, DOC, DOCX, TXT.",
                parse_mode='HTML',
            )
            return CP_DESCRIPTION

        try:
            tg_file = await document.get_file()
            file_bytes = await tg_file.download_as_bytearray()
            extracted_text = self._extract_text_from_file(bytes(file_bytes), file_name)

            if not extracted_text or len(extracted_text.strip()) < 10:
                await update.message.reply_text(
                    "⚠️ Не удалось извлечь текст из файла. Попробуйте другой формат."
                )
                return CP_DESCRIPTION

            descs = context.user_data.get('_cp', {}).get('descriptions', [])
            descs.append(f"[Файл: {document.file_name}]\n{extracted_text}")
            context.user_data['_cp']['descriptions'] = descs

            count = len(descs)
            await update.message.reply_text(
                f"✅ Файл <b>{document.file_name}</b> обработан ({count} фрагмент{'ов' if count > 1 else ''}).\n"
                "Можете отправить ещё или нажмите <b>Сделать коммерческое</b>.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Сделать коммерческое", callback_data="cp_generate")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
            )
        except Exception as e:
            logger.error(f"Failed to process uploaded file: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ Ошибка обработки файла: {str(e)[:200]}"
            )
        return CP_DESCRIPTION

    async def admin_cp_description_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice messages for project description — transcribe via Gemini."""
        voice = update.message.voice or update.message.audio
        if not voice:
            return CP_DESCRIPTION

        processing_msg = await update.message.reply_text(
            "🎙️ <b>Голосовое сообщение получено!</b>\n\n"
            "⏳ Распознаю речь через AI...",
            parse_mode='HTML',
        )

        try:
            tg_file = await context.bot.get_file(voice.file_id)
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
                temp_path = tmp.name
            await tg_file.download_to_drive(temp_path)

            transcription = await self.ai.transcribe_audio_gemini(temp_path)

            try:
                os.unlink(temp_path)
            except Exception:
                pass

            if transcription.startswith("Извините") or transcription.startswith("Ошибка"):
                await processing_msg.delete()
                await update.message.reply_text(
                    f"❌ {transcription}\n\nПопробуйте записать ещё раз или напишите текстом.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                    ]),
                )
                return CP_DESCRIPTION

            await processing_msg.delete()

            context.user_data['_cp_voice_text'] = transcription

            preview = transcription[:3000]
            if len(transcription) > 3000:
                preview += '...'

            await update.message.reply_text(
                f"🎙️ <b>Расшифровка голосового:</b>\n\n"
                f"<i>{preview}</i>\n\n"
                "Вы можете:\n"
                "• <b>Принять</b> — текст будет добавлен как ТЗ\n"
                "• <b>Редактировать</b> — отправьте исправленный текст следующим сообщением\n"
                "• Записать ещё одно голосовое",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Принять текст", callback_data="cp_voice_accept")],
                    [InlineKeyboardButton("✏️ Редактировать", callback_data="cp_voice_edit")],
                    [InlineKeyboardButton("🗑 Отклонить", callback_data="cp_voice_discard")],
                ]),
                parse_mode='HTML',
            )
            return CP_DESCRIPTION

        except Exception as e:
            logger.error(f"Voice transcription in CP failed: {e}", exc_info=True)
            try:
                await processing_msg.delete()
            except Exception:
                pass
            await update.message.reply_text(
                f"❌ Ошибка распознавания: {str(e)[:200]}\n\nПопробуйте ещё раз или напишите текстом.",
            )
            return CP_DESCRIPTION

    async def admin_cp_voice_accept(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Accept transcribed voice text as project description."""
        query = update.callback_query
        await query.answer()

        transcription = context.user_data.pop('_cp_voice_text', '')
        if not transcription:
            await query.edit_message_text("⚠️ Текст расшифровки не найден. Отправьте голосовое ещё раз.")
            return CP_DESCRIPTION

        descs = context.user_data.get('_cp', {}).get('descriptions', [])
        descs.append(transcription)
        context.user_data['_cp']['descriptions'] = descs

        count = len(descs)
        await query.edit_message_text(
            f"✅ Голосовое принято ({count} фрагмент{'ов' if count > 1 else ''}).\n"
            "Можете отправить ещё (текст, файл или голосовое) или нажмите <b>Сделать коммерческое</b>.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Сделать коммерческое", callback_data="cp_generate")],
                [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
            ]),
            parse_mode='HTML',
        )
        return CP_DESCRIPTION

    async def admin_cp_voice_edit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Switch to edit mode — next text message replaces the transcription."""
        query = update.callback_query
        await query.answer()

        context.user_data['_cp_voice_editing'] = True

        await query.edit_message_text(
            "✏️ <b>Режим редактирования</b>\n\n"
            "Отправьте исправленный текст следующим сообщением.\n"
            "Он заменит расшифровку голосового.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="cp_voice_discard")],
            ]),
            parse_mode='HTML',
        )
        return CP_DESCRIPTION

    async def admin_cp_voice_discard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Discard the voice transcription."""
        query = update.callback_query
        await query.answer()

        context.user_data.pop('_cp_voice_text', None)
        context.user_data.pop('_cp_voice_editing', None)

        descs = context.user_data.get('_cp', {}).get('descriptions', [])
        count = len(descs)
        status = f"На данный момент: {count} фрагмент{'ов' if count > 1 else ''}." if count > 0 else "Пока описания нет."

        await query.edit_message_text(
            f"🗑 Расшифровка отклонена.\n{status}\n\n"
            "Отправьте текст, файл или голосовое сообщение.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Сделать коммерческое", callback_data="cp_generate")] if count > 0 else [],
                [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
            ]),
            parse_mode='HTML',
        )
        return CP_DESCRIPTION

    def _extract_text_from_file(self, file_bytes: bytes, file_name: str) -> str:
        """Extract text from uploaded file."""
        file_name_lower = file_name.lower()

        if file_name_lower.endswith('.pdf'):
            return self._extract_text_from_pdf(file_bytes)
        elif file_name_lower.endswith(('.doc', '.docx')):
            return self._extract_text_from_docx(file_bytes)
        elif file_name_lower.endswith(('.txt', '.md', '.rtf')):
            try:
                return file_bytes.decode('utf-8')
            except UnicodeDecodeError:
                return file_bytes.decode('cp1251', errors='replace')
        return ""

    @staticmethod
    def _extract_text_from_pdf(file_bytes: bytes) -> str:
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(file_bytes))
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.error(f"PDF text extraction failed: {e}")
            return ""

    @staticmethod
    def _extract_text_from_docx(file_bytes: bytes) -> str:
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            logger.error(f"DOCX text extraction failed: {e}")
            return ""

    async def admin_cp_generate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm and generate the commercial proposal."""
        query = update.callback_query
        await query.answer()

        cp = context.user_data.get('_cp', {})
        descriptions = cp.get('descriptions', [])

        if not descriptions:
            await query.edit_message_text(
                "❌ Вы не отправили описание проекта.\n"
                "Пожалуйста, напишите текст или загрузите файл.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Назад", callback_data="cp_back_to_description")],
                ]),
                parse_mode='HTML',
            )
            return CP_DESCRIPTION

        full_description = "\n\n".join(descriptions)
        cp_type = cp.get('type', 'full')
        design = cp.get('design', 'full_design')
        hourly_rate = cp.get('hourly_rate', 35)
        currency = cp.get('currency', '$')
        budget = cp.get('budget')
        budget_currency = cp.get('budget_currency')
        client_name = cp.get('client_name', '')

        type_label = "MVP" if cp_type == "mvp" else "Полноценный"
        design_labels = {
            "full_design": "Полный дизайн",
            "wireframes": "Вайрфреймы",
            "no_design": "Без дизайна",
        }
        design_label = design_labels.get(design, design)

        summary = (
            "📄 <b>Генерация коммерческого предложения</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"• Тип: <b>{type_label}</b>\n"
            f"• Дизайн: <b>{design_label}</b>\n"
            f"• Ставка: <b>{hourly_rate:,.0f} {currency}/час</b>\n"
        )
        if budget:
            summary += f"• Бюджет: <b>{budget:,.0f} {budget_currency}</b>\n"
        if client_name:
            summary += f"• Клиент: <b>{client_name}</b>\n"
        summary += f"• Описание: <b>{len(full_description)} символов</b>\n"

        await query.edit_message_text(
            summary + "\n⏳ <b>Генерирую расчёт... Это может занять 1-2 минуты.</b>",
            parse_mode='HTML',
        )

        try:
            estimation = await self.proposal_calculator.calculate_proposal(
                project_description=full_description,
                proposal_type=cp_type,
                budget_constraint=budget,
                budget_currency=budget_currency,
                design_type=design,
                hourly_rate=hourly_rate,
                currency=currency,
            )

            if estimation.get("error"):
                raise ValueError(estimation.get("error_message", "Ошибка расчёта"))

            estimation['client_name'] = client_name
            is_seller = context.user_data.get('is_seller', False)
            creator_username = (update.effective_user.username or '').lstrip('@')

            if is_seller:
                ceo_contact = self.config.STAFF_CONTACTS.get('black_tie_777')
                creator_contact = ceo_contact or {
                    'name': self.config.company_name or 'НейроСофт',
                    'role': 'CEO',
                    'phone': self.config.company_phone or '',
                    'email': self.config.company_email or 'info@rusneurosoft.ru',
                    'telegram': self.config.company_telegram or '',
                }
            else:
                creator_contact = self.config.STAFF_CONTACTS.get(creator_username)
                if not creator_contact:
                    creator_contact = {
                        'name': f"{update.effective_user.first_name or ''} {update.effective_user.last_name or ''}".strip(),
                        'role': '',
                        'phone': self.config.company_phone or '',
                        'email': self.config.company_email or 'info@rusneurosoft.ru',
                        'telegram': f"@{creator_username}" if creator_username else '',
                    }

            config_data = {
                'company_name': self.config.company_name or 'НейроСофт',
                'company_email': self.config.company_email or 'info@rusneurosoft.ru',
                'company_website': self.config.company_website or 'https://rusneurosoft.ru/',
                'company_phone': self.config.company_phone or '',
                'company_telegram': self.config.company_telegram or '',
                'creator': creator_contact,
            }

            import uuid as _uuid
            token = _uuid.uuid4().hex[:16]
            project_name = estimation.get("project_name", "КП")

            await self.db.save_commercial_proposal(
                token=token,
                project_name=project_name,
                client_name=client_name,
                proposal_type=cp_type,
                design_type=design,
                currency=currency,
                hourly_rate=hourly_rate,
                estimation=estimation,
                config_data=config_data,
                created_by_telegram_id=update.effective_user.id,
            )

            proposal_url = f"{self.config.webapp_url}/proposal/{token}"

            totals = estimation.get("totals", {})
            raw_hours = totals.get("total_hours", 0)
            raw_cost = totals.get("total_cost", 0)
            timeline = estimation.get("timeline_months", {})

            if isinstance(raw_hours, dict):
                hours_str = f"{raw_hours.get('min', 0):,.0f} – {raw_hours.get('max', 0):,.0f}"
            else:
                hours_str = f"{int(raw_hours):,}"

            if isinstance(raw_cost, dict):
                cost_str = f"{_fmt_number_inline(raw_cost.get('min', 0), currency)} – {_fmt_number_inline(raw_cost.get('max', 0), currency)}"
            else:
                cost_str = _fmt_number_inline(int(raw_cost), currency)

            if isinstance(timeline, dict):
                timeline_str = f"{timeline.get('min', 0)} – {timeline.get('max', 0)} мес."
            else:
                weeks = estimation.get("timeline_weeks", 0)
                timeline_str = f"{weeks} нед." if weeks else "—"

            result_text = (
                "✅ <b>Коммерческое предложение сформировано!</b>\n\n"
                f"📋 Проект: <b>{project_name}</b>\n"
                f"⏱ Часы: <b>{hours_str}</b>\n"
                f"💰 Стоимость: <b>{cost_str}</b>\n"
                f"📅 Сроки: <b>{timeline_str}</b>\n\n"
                f"🔗 <a href=\"{proposal_url}\">Открыть КП</a>"
            )

            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=result_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Открыть КП", url=proposal_url)],
                    [InlineKeyboardButton("📄 Ещё одно КП", callback_data="admin_cp_start")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
                disable_web_page_preview=True,
            )

        except Exception as e:
            logger.error(f"Commercial proposal generation failed: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=f"❌ Ошибка генерации КП:\n<code>{str(e)[:400]}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data="admin_cp_start")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="staff_menu")],
                ]),
                parse_mode='HTML',
            )
        finally:
            context.user_data.pop('_cp', None)

        return STAFF_MENU

    async def admin_cp_back_to_budget(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Go back to budget question."""
        query = update.callback_query
        await query.answer()
        cp_type = context.user_data.get('_cp', {}).get('type', 'full')
        type_label = "MVP" if cp_type == "mvp" else "Полноценный"
        text = (
            f"📄 <b>Коммерческое предложение</b>\n"
            f"Тип: <b>{type_label}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Нужно ли подогнать под определённую сумму?"
        )
        keyboard = [
            [InlineKeyboardButton("💰 Да, есть бюджет", callback_data="cp_budget_yes")],
            [InlineKeyboardButton("📊 Нет, считать без ограничений", callback_data="cp_budget_no")],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_cp_start")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return CP_BUDGET

    async def admin_cp_back_to_design(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Go back to design question."""
        query = update.callback_query
        await query.answer()
        return await self._cp_ask_design(query, context)

    async def admin_cp_back_to_rate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Go back to hourly rate question."""
        query = update.callback_query
        await query.answer()
        text = (
            "📄 <b>Коммерческое предложение</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Укажите стоимость часа работы.\n"
            "Если сумма в рублях — расчёт будет в ₽,\n"
            "если в долларах — в $.\n\n"
            "Примеры: <code>35$</code> или <code>3000₽</code>"
        )
        keyboard = [
            [InlineKeyboardButton("◀️ Назад", callback_data="cp_back_to_design")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return CP_HOURLY_RATE

    async def admin_cp_back_to_client(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Go back to client name."""
        query = update.callback_query
        await query.answer()
        text = (
            "📄 <b>Название компании клиента</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Введите название компании клиента.\n"
            "Или нажмите <b>Пропустить</b>."
        )
        keyboard = [
            [InlineKeyboardButton("⏭ Пропустить", callback_data="cp_client_skip")],
            [InlineKeyboardButton("◀️ Назад", callback_data="cp_back_to_rate")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return CP_CLIENT_NAME

    async def admin_cp_back_to_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Go back to description input."""
        query = update.callback_query
        await query.answer()
        return await self._cp_ask_description(query, context)

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
    
    # Middleware to save all users who interact with the bot
    async def save_user_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Middleware to automatically save users to database"""
        if update.effective_user:
            user = update.effective_user
            try:
                await bot.db.save_user(
                    telegram_id=user.id,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    username=user.username,
                    language_code=user.language_code
                )
            except Exception as e:
                logger.error(f"Failed to save user {user.id} in middleware: {e}")
    
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
        entry_points=[
            CommandHandler("start", bot.start),
            CommandHandler("change_staff", bot.handle_staff_secret),
            CommandHandler("change_admin", bot.handle_admin_secret),
        ],
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
            STAFF_MENU: [
                CallbackQueryHandler(bot.staff_create_zoom_start, pattern="^staff_create_zoom$"),
                CallbackQueryHandler(bot.staff_my_meetings, pattern="^staff_my_meetings$"),
                CallbackQueryHandler(bot.zoom_share_invite, pattern="^zoom_share_invite$"),
                CallbackQueryHandler(bot.staff_zoom_reschedule_start, pattern="^zoom_reschedule_"),
                CallbackQueryHandler(bot.admin_view_staff, pattern="^admin_view_staff$"),
                CallbackQueryHandler(bot.admin_create_invite, pattern="^admin_create_invite$"),
                CallbackQueryHandler(bot.admin_report_menu, pattern="^admin_report_menu$"),
                CallbackQueryHandler(bot.admin_cp_start, pattern="^admin_cp_start$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            STAFF_MY_MEETINGS: [
                CallbackQueryHandler(bot.staff_zoom_cancel_execute, pattern="^zoom_cancel_yes_"),
                CallbackQueryHandler(bot.staff_zoom_cancel_confirm, pattern="^zoom_cancel_"),
                CallbackQueryHandler(bot.staff_zoom_reschedule_start, pattern="^zoom_reschedule_"),
                CallbackQueryHandler(bot.staff_my_meetings, pattern="^staff_my_meetings$"),
                CallbackQueryHandler(bot.staff_create_zoom_start, pattern="^staff_create_zoom$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            STAFF_ZOOM_TOPIC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.staff_zoom_topic_received),
            ],
            STAFF_ZOOM_DURATION: [
                CallbackQueryHandler(bot.staff_zoom_duration_selected, pattern="^zoom_dur_"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            STAFF_ZOOM_SCHEDULE: [
                CallbackQueryHandler(bot.staff_zoom_schedule_now, pattern="^zoom_schedule_now$"),
                CallbackQueryHandler(bot.staff_zoom_schedule_later, pattern="^zoom_schedule_later$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            STAFF_ZOOM_DATE: [
                CallbackQueryHandler(bot.staff_zoom_reschedule_now, pattern="^zoom_now$"),
                CallbackQueryHandler(bot.staff_zoom_date_selected, pattern="^zoom_date_"),
                CallbackQueryHandler(bot.staff_zoom_schedule_later, pattern="^zoom_schedule_later$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            STAFF_ZOOM_TIME: [
                CallbackQueryHandler(bot.staff_zoom_time_selected, pattern="^zoom_time_"),
                CallbackQueryHandler(bot.staff_zoom_schedule_later, pattern="^zoom_schedule_later$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            STAFF_ZOOM_PARTICIPANTS: [
                CallbackQueryHandler(bot.staff_zoom_toggle_participant, pattern="^zoom_participant_toggle_"),
                CallbackQueryHandler(bot.staff_zoom_participants_confirm, pattern="^zoom_participants_confirm$"),
                CallbackQueryHandler(bot.staff_zoom_participants_skip, pattern="^zoom_participants_skip$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            STAFF_ZOOM_PROJECT: [
                CallbackQueryHandler(bot.staff_zoom_project_choose, pattern="^zoom_project_choose$"),
                CallbackQueryHandler(bot.staff_zoom_project_selected, pattern="^zoom_project_pick_"),
                CallbackQueryHandler(bot.staff_zoom_project_skip, pattern="^zoom_project_skip$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            ADMIN_VIEW_STAFF: [
                CallbackQueryHandler(bot.admin_staff_profile, pattern="^admin_profile_"),
                CallbackQueryHandler(bot.admin_view_staff, pattern="^admin_view_staff$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            ADMIN_STAFF_PROFILE: [
                CallbackQueryHandler(bot.admin_note_select, pattern="^admin_note_(?!clear)"),
                CallbackQueryHandler(bot.admin_set_specialty, pattern="^admin_specialty_"),
                CallbackQueryHandler(bot.admin_staff_profile, pattern="^admin_profile_"),
                CallbackQueryHandler(bot.admin_view_staff, pattern="^admin_view_staff$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            ADMIN_EDIT_NOTE: [
                CallbackQueryHandler(bot.admin_note_clear, pattern="^admin_note_clear$"),
                CallbackQueryHandler(bot.admin_staff_profile, pattern="^admin_profile_"),
                CallbackQueryHandler(bot.admin_view_staff, pattern="^admin_view_staff$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.admin_note_text_received),
            ],
            ADMIN_SET_SPECIALTY: [
                CallbackQueryHandler(bot.admin_set_grade, pattern="^admin_spec_"),
                CallbackQueryHandler(bot.admin_staff_profile, pattern="^admin_profile_"),
                CallbackQueryHandler(bot.admin_view_staff, pattern="^admin_view_staff$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            ADMIN_SET_GRADE: [
                CallbackQueryHandler(bot.admin_grade_save, pattern="^admin_grade_save_"),
                CallbackQueryHandler(bot.admin_set_specialty, pattern="^admin_specialty_"),
                CallbackQueryHandler(bot.admin_staff_profile, pattern="^admin_profile_"),
                CallbackQueryHandler(bot.admin_view_staff, pattern="^admin_view_staff$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            ADMIN_REPORT_MENU: [
                CallbackQueryHandler(bot.admin_team_report_start, pattern="^admin_team_report$"),
                CallbackQueryHandler(bot.admin_client_report_start, pattern="^admin_client_report$"),
                CallbackQueryHandler(bot.admin_report_menu, pattern="^admin_report_menu$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            ADMIN_TEAM_REPORT_DATES: [
                CallbackQueryHandler(bot.admin_report_menu, pattern="^admin_report_menu$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.admin_team_report_dates_received),
            ],
            ADMIN_CLIENT_SELECT_CUSTOMER: [
                CallbackQueryHandler(bot.admin_client_select_customer, pattern="^client_pick_"),
                CallbackQueryHandler(bot.admin_report_menu, pattern="^admin_report_menu$"),
                CallbackQueryHandler(bot.admin_client_report_start, pattern="^admin_client_report$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            ADMIN_CLIENT_SELECT_PROJECTS: [
                CallbackQueryHandler(bot.admin_client_toggle_project, pattern="^client_proj_toggle_"),
                CallbackQueryHandler(bot.admin_client_confirm_projects, pattern="^client_proj_confirm$"),
                CallbackQueryHandler(bot.admin_client_report_start, pattern="^admin_client_report$"),
                CallbackQueryHandler(bot.admin_report_menu, pattern="^admin_report_menu$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            ADMIN_CLIENT_REPORT_DATES: [
                CallbackQueryHandler(bot.admin_client_report_start, pattern="^client_proj_back$"),
                CallbackQueryHandler(bot.admin_report_menu, pattern="^admin_report_menu$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.admin_client_report_dates_received),
            ],
            CP_TYPE: [
                CallbackQueryHandler(bot.admin_cp_type_selected, pattern="^cp_type_"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            CP_BUDGET: [
                CallbackQueryHandler(bot.admin_cp_budget_answer, pattern="^cp_budget_"),
                CallbackQueryHandler(bot.admin_cp_start, pattern="^admin_cp_start$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            CP_BUDGET_AMOUNT: [
                CallbackQueryHandler(bot.admin_cp_back_to_budget, pattern="^cp_back_to_budget$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.admin_cp_budget_amount_received),
            ],
            CP_DESIGN: [
                CallbackQueryHandler(bot.admin_cp_design_selected, pattern="^cp_design_"),
                CallbackQueryHandler(bot.admin_cp_back_to_budget, pattern="^cp_back_to_budget$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
            CP_HOURLY_RATE: [
                CallbackQueryHandler(bot.admin_cp_back_to_design, pattern="^cp_back_to_design$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.admin_cp_hourly_rate_received),
            ],
            CP_CLIENT_NAME: [
                CallbackQueryHandler(bot.admin_cp_client_skip, pattern="^cp_client_skip$"),
                CallbackQueryHandler(bot.admin_cp_back_to_rate, pattern="^cp_back_to_rate$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.admin_cp_client_name_received),
            ],
            CP_DESCRIPTION: [
                CallbackQueryHandler(bot.admin_cp_generate, pattern="^cp_generate$"),
                CallbackQueryHandler(bot.admin_cp_voice_accept, pattern="^cp_voice_accept$"),
                CallbackQueryHandler(bot.admin_cp_voice_edit, pattern="^cp_voice_edit$"),
                CallbackQueryHandler(bot.admin_cp_voice_discard, pattern="^cp_voice_discard$"),
                CallbackQueryHandler(bot.admin_cp_back_to_client, pattern="^cp_back_to_client$"),
                CallbackQueryHandler(bot.admin_cp_back_to_description, pattern="^cp_back_to_description$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
                MessageHandler(filters.VOICE | filters.AUDIO, bot.admin_cp_description_voice),
                MessageHandler(filters.Document.ALL, bot.admin_cp_description_file),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.admin_cp_description_text),
            ],
            CP_CONFIRM: [
                CallbackQueryHandler(bot.admin_cp_generate, pattern="^cp_generate$"),
                CallbackQueryHandler(bot.admin_cp_start, pattern="^admin_cp_start$"),
                CallbackQueryHandler(bot.staff_menu_callback, pattern="^staff_menu$"),
            ],
        },
        fallbacks=[
            CommandHandler("change_staff", bot.handle_staff_secret),
            CommandHandler("change_admin", bot.handle_admin_secret),
            CommandHandler("cancel", bot.cancel),
            CallbackQueryHandler(bot.contact_support, pattern="^contact_support$"),
        ],
    )
    
    # Add middleware to save all users (runs before other handlers)
    application.add_handler(
        MessageHandler(filters.ALL, save_user_middleware),
        group=-1
    )
    application.add_handler(
        CallbackQueryHandler(save_user_middleware),
        group=-1
    )
    
    application.add_handler(conv_handler)
    
    # Add roulette command handler
    application.add_handler(CommandHandler("roulette", bot.roulette_command))
    
    # Add web app data handler (for roulette results)
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, bot.handle_roulette_result))
    
    # Initialize database and register bot commands
    async def post_init(app: Application) -> None:
        """Initialize database, register commands, and re-schedule reminders."""
        await bot.initialize_db()
        commands = [
            BotCommand("start", "🏠 Главное меню"),
            BotCommand("cancel", "❌ Отменить текущее действие"),
        ]
        await app.bot.set_my_commands(commands)
        logger.info("Bot commands registered in menu")
        try:
            from telegram import MenuButtonCommands
            await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
            logger.info("Bot menu button set to commands")
        except Exception as e:
            logger.warning(f"Failed to set menu button: {e}")
        try:
            await bot.reschedule_meeting_reminders(app)
        except Exception as e:
            logger.error(f"Failed to reschedule meeting reminders: {e}")
    
    application.post_init = post_init
    
    # Start bot
    logger.info("Starting Neuro-Connector Bot...")
    application.run_polling()

if __name__ == '__main__':
    main()
