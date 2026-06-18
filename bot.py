import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from typing import Union

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import F
from aiogram.filters import BaseFilter
from aiogram.enums import ChatMemberStatus

import database as db

# ---------------------------- Конфигурация (жёстко) ----------------------------
BOT_TOKEN = "7843994635:AAGvFPidIKEDCcqKp5NVPgm1yfsdOOrwgrE"
OWNER_ID = 7839616999  # Твой Telegram ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Роли в порядке возрастания полномочий (для отображения)
ROLE_ORDER = ["moderator", "senior_mod", "admin", "owner"]
ROLE_NAMES = {
    "moderator": "Модератор",
    "senior_mod": "Старший модератор",
    "admin": "Администратор",
    "owner": "Главный администратор"
}

# ---------------------------- Фильтры ----------------------------
class IsGroup(BaseFilter):
    """Проверяет, что сообщение из группы или супергруппы."""
    async def __call__(self, message: Message) -> bool:
        return message.chat.type in ["group", "supergroup"]

class HasRole(BaseFilter):
    """Проверяет, что пользователь имеет указанную роль или выше (в чате)."""
    def __init__(self, min_role: str):
        self.min_role = min_role

    async def __call__(self, message: Message) -> bool:
        if not await IsGroup()(message):
            return False
        role = await db.get_user_role(message.from_user.id, message.chat.id)
        if not role:
            return False
        return await db.get_role_priority(role) >= await db.get_role_priority(self.min_role)

# ---------------------------- Middleware ----------------------------
@dp.message.outer_middleware()
async def count_messages_middleware(handler, event: Message, data: dict):
    """Считает текстовые сообщения (не команды) для пользователя в чате."""
    if event.text and not event.text.startswith('/') and event.chat.type in ["group", "supergroup"]:
        await db.ensure_user(event.from_user.id, event.from_user.username, event.from_user.first_name)
        await db.ensure_chat(event.chat.id, event.chat.title)
        await db.ensure_user_chat(event.from_user.id, event.chat.id)
        await db.increment_message(event.from_user.id, event.chat.id)
    return await handler(event, data)

# ---------------------------- Вспомогательные функции ----------------------------
async def is_bot_admin(chat_id: int) -> bool:
    """Проверяет, является ли бот администратором чата."""
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        return member.status == ChatMemberStatus.ADMINISTRATOR or member.status == ChatMemberStatus.CREATOR
    except:
        return False

async def check_bot_admin_and_warn(message: Message) -> bool:
    """Если бот не админ, отправляет предупреждение и возвращает False."""
    if not await is_bot_admin(message.chat.id):
        await message.answer("❌ Я не администратор чата, пожалуйста, выдайте мне права администратора.")
        return False
    return True

async def resolve_user(message: Message, args: str = None) -> Union[int, None]:
    """Извлекает user_id из ответа на сообщение или из аргумента @username/id."""
    target_id = None
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif args:
        arg = args.strip()
        if arg.startswith('@'):
            # Поиск username в чате (упрощённо, через get_chat_member)
            try:
                member = await bot.get_chat_member(message.chat.id, arg)
                target_id = member.user.id
            except:
                pass
        else:
            try:
                target_id = int(arg)
            except:
                pass
    return target_id

async def notify_admins(chat_id: int, text: str, reply_markup=None):
    """Рассылает сообщение всем админам чата в личку."""
    admins = await db.get_admins_by_chat(chat_id)
    for uid, role in admins:
        try:
            await bot.send_message(uid, text, reply_markup=reply_markup)
        except:
            pass

def make_report_keyboard(chat_id: int, reported_user_id: int, message_id: int):
    """Клавиатура для репорта с вариантами наказаний."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔨 Бан", callback_data=f"punish_{chat_id}_{reported_user_id}_{message_id}_ban")
    builder.button(text="🔇 Мут 1ч", callback_data=f"punish_{chat_id}_{reported_user_id}_{message_id}_mute60")
    builder.button(text="⚠️ Варн", callback_data=f"punish_{chat_id}_{reported_user_id}_{message_id}_warn")
    builder.button(text="✅ Отклонить", callback_data=f"punish_{chat_id}_{reported_user_id}_{message_id}_dismiss")
    builder.adjust(1)
    return builder.as_markup()

# ---------------------------- Команды ----------------------------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.type == "private":
        await message.answer("Привет! Я бот-модератор. Добавь меня в группу и назначь администратором.")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Показывает список команд в зависимости от роли."""
    user_id = message.from_user.id
    if message.chat.type in ["group", "supergroup"]:
        role = await db.get_user_role(user_id, message.chat.id)
        chat_id = message.chat.id
    else:
        role = None
        chat_id = None

    text = "<b>📚 Список доступных команд</b>\n\n"
    # Базовые для всех
    text += "ℹ️ <b>Общие</b>\n"
    text += "/id – Узнать ID\n"
    text += "/info [@user] – Информация о пользователе\n"
    text += "/help – Эта справка\n"
    if message.chat.type in ["group", "supergroup"]:
        text += "/report [причина] – Пожаловаться на сообщение (ответом)\n"
        text += "/stats – Статистика сообщений\n"
    # Модератор+
    if role and await db.get_role_priority(role) >= await db.get_role_priority("moderator"):
        text += "\n🛡️ <b>Модерация (moderator+)</b>\n"
        text += "/mute [мин] – Замутить (ответом или @user)\n"
        text += "/unmute – Размутить\n"
        text += "/warn – Предупреждение\n"
        text += "/unwarn – Снять предупреждения\n"
    # Старший модератор+
    if role and await db.get_role_priority(role) >= await db.get_role_priority("senior_mod"):
        text += "\n🔨 <b>Старший модератор+</b>\n"
        text += "/ban – Забанить навсегда\n"
        text += "/unban – Разбанить\n"
        text += "/del – Удалить сообщение (ответом)\n"
        text += "/admins – Список админов с ролями\n"
    # Администратор+
    if role and await db.get_role_priority(role) >= await db.get_role_priority("admin"):
        text += "\n👑 <b>Администратор+</b>\n"
        text += "/promote @user роль – Назначить роль\n"
        text += "/demote @user – Снять с должности\n"
        text += "/clearwarns @user – Обнулить варны\n"
    # Владелец (глобальный или чата)
    if (role == "owner") or (user_id == OWNER_ID):
        text += "\n🌟 <b>Владелец</b>\n"
        text += "/botlog – Получить логи (только глобальный владелец)\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("id"))
async def cmd_id(message: Message):
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        await message.answer(f"👤 ID пользователя: <code>{user.id}</code>\n💬 ID чата: <code>{message.chat.id}</code>", parse_mode="HTML")
    else:
        if message.chat.type == "private":
            await message.answer(f"🆔 Ваш ID: <code>{message.from_user.id}</code>", parse_mode="HTML")
        else:
            await message.answer(f"💬 ID чата: <code>{message.chat.id}</code>", parse_mode="HTML")

@dp.message(Command("info"))
async def cmd_info(message: Message, command: CommandObject):
    """Карточка пользователя в чате или сводка по чатам в ЛС."""
    user_id = message.from_user.id
    if message.chat.type == "private":
        # ЛС: показать все чаты, где пользователь состоит админом
        chats = await db.get_user_chats_with_role(user_id)
        if not chats:
            await message.answer("Вы не являетесь администратором ни в одном чате.")
            return
        text = "<b>📋 Ваши административные роли:</b>\n"
        for chat_id, role, title in chats:
            text += f"• {title} (<code>{chat_id}</code>) — {ROLE_NAMES.get(role, role)}\n"
        await message.answer(text, parse_mode="HTML")
        return

    # В чате: нужен target
    target_id = await resolve_user(message, command.args)
    if not target_id:
        await message.answer("❌ Укажите пользователя: @username или ответ на сообщение.")
        return
    info = await db.get_user_status(target_id, message.chat.id)
    if not info:
        await message.answer("Пользователь не найден в базе чата.")
        return
    role = await db.get_user_role(target_id, message.chat.id)
    username = (await bot.get_chat_member(message.chat.id, target_id)).user.username
    text = f"👤 <b>Пользователь:</b> @{username or 'нет'}\n"
    text += f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
    text += f"📅 <b>Первое сообщение:</b> {info['first_seen']}\n"
    text += f"💬 <b>Сообщений:</b> {info['message_count']}\n"
    text += f"⚠️ <b>Варнов:</b> {info['warn_count']}\n"
    text += f"🔹 <b>Статус:</b> {info['status']}\n"
    if role:
        text += f"👮 <b>Роль:</b> {ROLE_NAMES.get(role, role)}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эту команду можно использовать только в группах.")
        return
    top_all = await db.get_top_messages(message.chat.id)
    top_week = await db.get_top_messages(message.chat.id, days=7)
    text = "📊 <b>Топ-10 по сообщениям (всё время)</b>\n"
    for i, (uid, cnt) in enumerate(top_all, 1):
        try:
            member = await bot.get_chat_member(message.chat.id, uid)
            name = f"@{member.user.username}" if member.user.username else member.user.first_name
        except:
            name = str(uid)
        text += f"{i}. {name} — {cnt} сообщ.\n"
    text += "\n📅 <b>За последние 7 дней</b>\n"
    for i, (uid, cnt) in enumerate(top_week, 1):
        try:
            member = await bot.get_chat_member(message.chat.id, uid)
            name = f"@{member.user.username}" if member.user.username else member.user.first_name
        except:
            name = str(uid)
        text += f"{i}. {name} — {cnt} сообщ.\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("admins"))
async def cmd_admins(message: Message):
    if message.chat.type == "private":
        return await cmd_info(message)  # используем info для ЛС
    user_role = await db.get_user_role(message.from_user.id, message.chat.id)
    if not user_role or await db.get_role_priority(user_role) < await db.get_role_priority("senior_mod"):
        # Модератор: показывает только модераторов и выше, но без ролей
        admins = await db.get_admins_by_chat(message.chat.id)
        mods = []
        for uid, role in admins:
            if await db.get_role_priority(role) >= await db.get_role_priority("moderator"):
                try:
                    member = await bot.get_chat_member(message.chat.id, uid)
                    name = f"@{member.user.username}" if member.user.username else member.user.first_name
                except:
                    name = str(uid)
                mods.append(name)
        await message.answer("👮 Список модераторов и старших:\n" + ", ".join(mods) if mods else "Нет администраторов.")
    else:
        # Старший модератор+ видит полный список по ролям
        admins = await db.get_admins_by_chat(message.chat.id)
        grouped = {}
        for uid, role in admins:
            grouped.setdefault(role, []).append(uid)
        text = "👥 <b>Администраторы чата:</b>\n"
        for role in ["owner", "admin", "senior_mod", "moderator"]:
            uids = grouped.get(role, [])
            names = []
            for uid in uids:
                try:
                    member = await bot.get_chat_member(message.chat.id, uid)
                    name = f"@{member.user.username}" if member.user.username else member.user.first_name
                except:
                    name = str(uid)
                names.append(name)
            if names:
                text += f"<b>{ROLE_NAMES[role]}:</b> {', '.join(names)}\n"
        await message.answer(text, parse_mode="HTML")

# ---------------------------- Модерация ----------------------------
@dp.message(Command("mute"), IsGroup(), HasRole("moderator"))
async def cmd_mute(message: Message, command: CommandObject):
    if not await check_bot_admin_and_warn(message): return
    target_id = await resolve_user(message, command.args)
    if not target_id:
        await message.answer("❌ Укажите пользователя ответом или @username.")
        return
    actor_role = await db.get_user_role(message.from_user.id, message.chat.id)
    target_role = await db.get_user_role(target_id, message.chat.id)
    if target_role and not await is_higher_or_equal(actor_role, target_role):
        await message.answer("❌ Недостаточно прав для мута этого пользователя.")
        return
    try:
        minutes = int(command.args.split()[-1]) if command.args and command.args.split()[-1].isdigit() else 60
    except:
        minutes = 60
    minutes = max(1, min(minutes, 43200))
    await bot.restrict_chat_member(message.chat.id, target_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=datetime.now() + timedelta(minutes=minutes))
    await db.set_mute(target_id, message.chat.id, minutes)
    await db.log_action(message.chat.id, message.from_user.id, "mute", target_id, f"{minutes} мин")
    await message.answer(f"🔇 Пользователь замучен на {minutes} мин.")

@dp.message(Command("unmute"), IsGroup(), HasRole("moderator"))
async def cmd_unmute(message: Message, command: CommandObject):
    if not await check_bot_admin_and_warn(message): return
    target_id = await resolve_user(message, command.args)
    if not target_id:
        await message.answer("❌ Укажите пользователя.")
        return
    await bot.restrict_chat_member(message.chat.id, target_id, permissions=types.ChatPermissions(can_send_messages=True))
    await db.clear_mute(target_id, message.chat.id)
    await db.log_action(message.chat.id, message.from_user.id, "unmute", target_id)
    await message.answer("🔊 Пользователь размучен.")

@dp.message(Command("warn"), IsGroup(), HasRole("moderator"))
async def cmd_warn(message: Message, command: CommandObject):
    target_id = await resolve_user(message, command.args)
    if not target_id:
        await message.answer("❌ Укажите пользователя.")
        return
    actor_role = await db.get_user_role(message.from_user.id, message.chat.id)
    target_role = await db.get_user_role(target_id, message.chat.id)
    if target_role and not await is_higher_or_equal(actor_role, target_role):
        await message.answer("❌ Недостаточно прав.")
        return
    new_count = await db.add_warn(target_id, message.chat.id)
    await db.log_action(message.chat.id, message.from_user.id, "warn", target_id)
    text = f"⚠️ Предупреждение #{new_count} выдано."
    if new_count >= 5:
        await bot.ban_chat_member(message.chat.id, target_id, revoke_messages=True)
        await db.set_ban(target_id, message.chat.id)
        text += " Пользователь забанен (5 варнов)."
    elif new_count >= 3:
        await bot.restrict_chat_member(message.chat.id, target_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=datetime.now() + timedelta(hours=24))
        await db.set_mute(target_id, message.chat.id, 1440)
        text += " Пользователь замучен на 24 часа (3 варна)."
    await message.answer(text)

@dp.message(Command("unwarn"), IsGroup(), HasRole("moderator"))
async def cmd_unwarn(message: Message, command: CommandObject):
    target_id = await resolve_user(message, command.args)
    if not target_id:
        await message.answer("❌ Укажите пользователя.")
        return
    parts = command.args.split() if command.args else []
    count = int(parts[-1]) if parts and parts[-1].isdigit() else 1
    await db.remove_warns(target_id, message.chat.id, count)
    await db.log_action(message.chat.id, message.from_user.id, "unwarn", target_id, str(count))
    await message.answer(f"☑️ Снято {count} предупреждений.")

@dp.message(Command("ban"), IsGroup(), HasRole("senior_mod"))
async def cmd_ban(message: Message, command: CommandObject):
    if not await check_bot_admin_and_warn(message): return
    target_id = await resolve_user(message, command.args)
    if not target_id:
        await message.answer("❌ Укажите пользователя.")
        return
    actor_role = await db.get_user_role(message.from_user.id, message.chat.id)
    target_role = await db.get_user_role(target_id, message.chat.id)
    if target_role and not await is_higher_or_equal(actor_role, target_role):
        await message.answer("❌ Недостаточно прав.")
        return
    await bot.ban_chat_member(message.chat.id, target_id, revoke_messages=True)
    await db.set_ban(target_id, message.chat.id)
    await db.log_action(message.chat.id, message.from_user.id, "ban", target_id)
    await message.answer("🚫 Пользователь забанен навсегда.")

@dp.message(Command("unban"), IsGroup(), HasRole("senior_mod"))
async def cmd_unban(message: Message, command: CommandObject):
    if not await check_bot_admin_and_warn(message): return
    target_id = await resolve_user(message, command.args)
    if not target_id:
        await message.answer("❌ Укажите пользователя.")
        return
    await bot.unban_chat_member(message.chat.id, target_id)
    await db.clear_ban(target_id, message.chat.id)
    await db.log_action(message.chat.id, message.from_user.id, "unban", target_id)
    await message.answer("✅ Пользователь разбанен.")

@dp.message(Command("del"), IsGroup(), HasRole("senior_mod"))
async def cmd_del(message: Message):
    if not await check_bot_admin_and_warn(message): return
    if not message.reply_to_message:
        await message.answer("❌ Ответьте на сообщение, которое нужно удалить.")
        return
    await message.reply_to_message.delete()
    await db.log_action(message.chat.id, message.from_user.id, "delete", message.reply_to_message.from_user.id, message.reply_to_message.text[:100] if message.reply_to_message.text else "")
    await message.answer("🗑 Сообщение удалено.")

@dp.message(Command("report"), IsGroup())
async def cmd_report(message: Message, command: CommandObject):
    if not message.reply_to_message:
        await message.answer("❌ Ответьте на сообщение, чтобы пожаловаться.")
        return
    reason = command.args or "не указана"
    reported_user = message.reply_to_message.from_user
    text = f"⚠️ <b>Жалоба</b>\n"
    text += f"От: {message.from_user.mention}\n"
    text += f"На: {reported_user.mention}\n"
    text += f"Причина: {reason}\n"
    text += f"<a href='https://t.me/{message.chat.username}/{message.reply_to_message.message_id}'>Перейти к сообщению</a>" if message.chat.username else f"Сообщение в чате {message.chat.id}/{message.reply_to_message.message_id}"
    keyboard = make_report_keyboard(message.chat.id, reported_user.id, message.reply_to_message.message_id)
    await notify_admins(message.chat.id, text, reply_markup=keyboard)
    await message.answer("✅ Жалоба отправлена администраторам.")

# ---------------------------- Inline обработка репорта ----------------------------
@dp.callback_query(F.data.startswith("punish_"))
async def handle_punish_action(callback: CallbackQuery):
    _, chat_id_str, target_id_str, msg_id_str, action = callback.data.split("_")
    chat_id = int(chat_id_str)
    target_id = int(target_id_str)
    msg_id = int(msg_id_str)
    admin_id = callback.from_user.id
    admin_role = await db.get_user_role(admin_id, chat_id)
    if not admin_role:
        await callback.answer("Вы не администратор этого чата.", show_alert=True)
        return
    target_role = await db.get_user_role(target_id, chat_id)
    if target_role and not await is_higher_or_equal(admin_role, target_role):
        await callback.answer("Недостаточно прав для наказания.", show_alert=True)
        return
    if action == "ban" and await db.get_role_priority(admin_role) >= await db.get_role_priority("senior_mod"):
        await bot.ban_chat_member(chat_id, target_id, revoke_messages=True)
        await db.set_ban(target_id, chat_id)
        await db.log_action(chat_id, admin_id, "ban", target_id)
        text = "🚫 Забанен"
    elif action.startswith("mute") and await db.get_role_priority(admin_role) >= await db.get_role_priority("moderator"):
        minutes = int(action[4:]) if action[4:].isdigit() else 60
        await bot.restrict_chat_member(chat_id, target_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=datetime.now() + timedelta(minutes=minutes))
        await db.set_mute(target_id, chat_id, minutes)
        await db.log_action(chat_id, admin_id, "mute", target_id, f"{minutes} мин")
        text = f"🔇 Замучен на {minutes} мин"
    elif action == "warn" and await db.get_role_priority(admin_role) >= await db.get_role_priority("moderator"):
        await db.add_warn(target_id, chat_id)
        await db.log_action(chat_id, admin_id, "warn", target_id)
        text = "⚠️ Выдано предупреждение"
    elif action == "dismiss":
        text = "❌ Жалоба отклонена"
    else:
        await callback.answer("Недостаточно прав для этого действия.", show_alert=True)
        return
    await callback.message.edit_text(callback.message.text + f"\n\n✅ Реакция: {text}")
    await callback.answer("Готово")

# ---------------------------- Административные команды ----------------------------
@dp.message(Command("promote"), IsGroup(), HasRole("admin"))
async def cmd_promote(message: Message, command: CommandObject):
    args = command.args.split() if command.args else []
    if len(args) < 2:
        await message.answer("❌ Формат: /promote @user роль (moderator/senior_mod/admin)")
        return
    target_id = await resolve_user(message, args[0])
    role = args[1].lower()
    if role not in ["moderator", "senior_mod", "admin"]:
        await message.answer("❌ Неверная роль. Доступные: moderator, senior_mod, admin")
        return
    if not target_id:
        await message.answer("❌ Пользователь не найден.")
        return
    actor_role = await db.get_user_role(message.from_user.id, message.chat.id)
    if await db.get_role_priority(role) >= await db.get_role_priority(actor_role) and actor_role != 'owner':
        await message.answer("❌ Вы не можете выдавать роль выше или равную вашей.")
        return
    await db.add_admin(target_id, message.chat.id, role)
    await db.log_action(message.chat.id, message.from_user.id, "promote", target_id, role)
    await message.answer(f"✅ Пользователь назначен как {ROLE_NAMES[role]}")

@dp.message(Command("demote"), IsGroup(), HasRole("admin"))
async def cmd_demote(message: Message, command: CommandObject):
    target_id = await resolve_user(message, command.args)
    if not target_id:
        await message.answer("❌ Укажите пользователя.")
        return
    actor_role = await db.get_user_role(message.from_user.id, message.chat.id)
    target_role = await db.get_user_role(target_id, message.chat.id)
    if not target_role:
        await message.answer("❌ У пользователя нет роли.")
        return
    if not await is_higher_or_equal(actor_role, target_role) or target_role == "owner":
        await message.answer("❌ Недостаточно прав.")
        return
    await db.remove_admin(target_id, message.chat.id)
    await db.log_action(message.chat.id, message.from_user.id, "demote", target_id)
    await message.answer("✅ Пользователь снят с должности.")

@dp.message(Command("clearwarns"), IsGroup(), HasRole("admin"))
async def cmd_clearwarns(message: Message, command: CommandObject):
    target_id = await resolve_user(message, command.args)
    if not target_id:
        await message.answer("❌ Укажите пользователя.")
        return
    await db.clear_warns(target_id, message.chat.id)
    await db.log_action(message.chat.id, message.from_user.id, "clearwarns", target_id)
    await message.answer("☑️ Все предупреждения сброшены.")

@dp.message(Command("botlog"))
async def cmd_botlog(message: Message):
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ Только глобальный владелец может использовать эту команду.")
        return
    logs = await db.get_logs(100)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        for log in reversed(logs):
            f.write(f"{log}\n")
        f.flush()
        await message.answer_document(types.FSInputFile(f.name), caption="Последние 100 записей логов")
    os.unlink(f.name)

# ---------------------------- Обработчики событий чата ----------------------------
@dp.my_chat_member()
async def on_chat_member_update(event: types.ChatMemberUpdated):
    """При добавлении бота в чат делает пользователя owner'ом."""
    if event.new_chat_member.status in ["member", "administrator"] and event.old_chat_member.status not in ["member", "administrator"]:
        await db.ensure_chat(event.chat.id, event.chat.title)
        # Проверяем, нет ли уже owner'а
        admins = await db.get_admins_by_chat(event.chat.id)
        if not any(role == "owner" for _, role in admins):
            await db.add_admin(event.from_user.id, event.chat.id, "owner")

@dp.message(F.migrate_to_chat_id)
async def on_migration(message: Message):
    old_id = message.chat.id
    new_id = message.migrate_to_chat_id
    await db.migrate_chat(old_id, new_id)
    await message.answer("🔄 Чат мигрирован, база данных обновлена.")

# ---------------------------- Запуск ----------------------------
async def main():
    await db.init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
