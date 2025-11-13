from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from core.logger import bot_logger as logger
from bot.filters.admin import IsAdmin
from bot.templates.admin import menu as tadmin
from bot.templates.admin.menu import AdminRegState
from bot.templates.user.menu import user_reply_ikb
from config import cnf
from db.beanie.models import Claim, AdminMessage, KonsolPayment
from core.bot import bot, bot_config
from db.beanie.models.models import MOSCOW_TZ, ChatSession, UserMessage, Administrators
from utils.konsol_client import konsol_client
from utils.pending_storage import pending_actions

router = Router()

@router.message(Command("reg"), IsAdmin())
async def reg_admin(msg: Message, state: FSMContext):
    await state.clear()

    admin_id = msg.from_user.id

    # === Находим или создаём пользователя ===
    try:
        admin = await Administrators.get(admin_id=admin_id)
        await  msg.answer(f"Ваши данные для входа:\nЛогин: {admin.login}\nПароль: {admin.password}")
    except Exception as e:
        await msg.answer("Введите логин")
        await state.set_state(AdminRegState.waiting_for_login)




@router.message(StateFilter(AdminRegState.waiting_for_login))
async def process_login(msg: Message, state: FSMContext):
    if not msg.text:
        await msg.answer(
            "❌ Пожалуйста, отправьте корректный логин."
        )
        return
    login = msg.text.strip()

    await msg.answer("Введите пароль")
    await state.update_data(login=login)
    await state.set_state(AdminRegState.waiting_for_password)

@router.message(StateFilter(AdminRegState.waiting_for_password))
async def process_login(msg: Message, state: FSMContext):
    if not msg.text:
        await msg.answer(
            "❌ Пожалуйста, отправьте корректный пароль."
        )
        return
    admin_id = msg.from_user.id
    password = msg.text.strip()
    data = await state.get_data()
    login = data.get("login")
    try:
        await Administrators.create(
            admin_id=admin_id,
            login=login,
            password=password
        )
        await state.clear()

        await msg.answer("Регистрация прошла успешно.")
    except Exception as e:
        await msg.answer("Ошибка регистрации пользователя.")
        logger.error(f"{e} Ошибка регистрации пользователя.")

