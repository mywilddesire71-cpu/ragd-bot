import sys, faulthandler
faulthandler.enable(file=sys.stdout)
print("BOOT", sys.version, __file__, flush=True)

def mem():
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current",
              "/sys/fs/cgroup/memory/memory.limit_in_bytes",
              "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
        try:
            print(p, open(p).read().strip(), flush=True)
        except Exception:
            pass

mem()
for name in ["asyncio", "os", "logging", "traceback", "aiohttp", "aiosqlite", "pydantic", "aiogram"]:
    print("importing", name, flush=True)
    __import__(name)
    print("ok", name, flush=True)
mem()

import asyncio
import os
import logging
import traceback
import aiosqlite
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, URLInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

print("IMPORTS OK", flush=True)

# --- ЛОГИРОВАНИЕ (ПРИНУДИТЕЛЬНЫЙ ВЫВОД В КОНСОЛЬ) ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    stream=sys.stdout,
    force=True
)
logger = logging.getLogger(__name__)

# --- НАСТРОЙКИ ---
BOT_TOKEN = (
    os.getenv("BOT_TOKEN")
    or os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or os.getenv("TOKEN")
)
DB_PATH = "users.db"

OWNER_ID = 2046978907
CHANNEL_ID = "@TMRagdollSoccer"
ADMIN_CHAT_ID = -1004376666585

if not BOT_TOKEN:
    logger.error("❌ КРИТИЧЕСКАЯ ОШИБКА: Переменная BOT_TOKEN не найдена!")
    sys.stdout.flush()
    import time
    time.sleep(3600)
    sys.exit(1)

logger.info("✅ Токен успешно загружен.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

POSITIONS = {"Вратарь": "🧤", "Защитник": "🛡️", "Полузащитник": "🎯", "Нападающий": "⚡"}
APP_TYPES = {"free_agent": "Свободный агент", "club_app": "Заявка на клуб", "admin_app": "Заявка в администрацию", "nick_change": "Смена ника", "career_finish": "Завершение карьеры", "player_transfer": "Трансфер игрока", "club_search": "Поиск игроков (Клуб)", "friendly_match": "Поиск товы", "ad": "Объявление / Реклама"}

async def safe_edit_text(message: Message, text: str, reply_markup=None, parse_mode="HTML"):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        pass

class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return await is_admin(event.from_user.id)

class Form(StatesGroup):
    waiting_for_roblox_nick = State()
    entering_requirements = State()
    entering_contact = State()
    changing_nick = State()
    career_finish_reason = State()
    club_app_name = State()
    club_app_logo = State()
    admin_app_position = State()
    admin_app_experience = State()
    invite_player_target = State()
    friendly_format = State()
    friendly_time = State()
    club_search_positions = State()
    club_search_requirements = State()
    entering_ticket_text = State()
    entering_ticket_reply = State()
    entering_new_admin_id = State()
    entering_rename_club = State()
    entering_ad_text = State()
    entering_ad_link = State()

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS clubs (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, logo_id TEXT, owner_id INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, roblox_username TEXT NOT NULL, roblox_id INTEGER, display_name TEXT, position TEXT DEFAULT 'Не выбрана', career_status TEXT DEFAULT 'Активна', telegram_username TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS contracts (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER, club_id INTEGER, squad_type TEXT DEFAULT 'Основа', UNIQUE(telegram_id, club_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS applications (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER, type TEXT, text1 TEXT, text2 TEXT, text3 TEXT, status TEXT DEFAULT 'pending', created_at DATETIME)")
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, status TEXT DEFAULT 'open')")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (telegram_id INTEGER PRIMARY KEY, added_by INTEGER)")

        try: await db.execute("ALTER TABLE users ADD COLUMN position TEXT DEFAULT 'Не выбрана'")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN career_status TEXT DEFAULT 'Активна'")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN telegram_username TEXT")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE applications ADD COLUMN created_at DATETIME")
        except aiosqlite.OperationalError: pass

        try: await db.execute("INSERT INTO settings (key, value) VALUES ('admin_apps_open', 'True')")
        except aiosqlite.IntegrityError: pass
        await db.commit()
    logger.info("✅ База данных успешно инициализирована.")

async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID: return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM admins WHERE telegram_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def notify_admins(text: str, reply_markup=None, photo=None):
    try:
        if photo: await bot.send_photo(OWNER_ID, photo=photo, caption=text, parse_mode="HTML", reply_markup=reply_markup)
        else: await bot.send_message(OWNER_ID, text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e: logger.error(f"Ошибка отправки владельцу: {e}")
    try:
        if photo: await bot.send_photo(ADMIN_CHAT_ID, photo=photo, caption=text, parse_mode="HTML", reply_markup=reply_markup)
        else: await bot.send_message(ADMIN_CHAT_ID, text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e: logger.error(f"Ошибка отправки в чат: {e}")

async def check_limit(telegram_id: int, app_type: str, daily_limit: int, cooldown_hours: float) -> tuple[bool, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        if daily_limit > 0:
            async with db.execute("SELECT COUNT(*) FROM applications WHERE telegram_id = ? AND type = ? AND date(created_at) = date('now')", (telegram_id, app_type)) as cursor:
                if (await cursor.fetchone())[0] >= daily_limit:
                    return False, f"❌ Дневной лимит ({daily_limit} раз(а))."
        if cooldown_hours > 0:
            async with db.execute("SELECT created_at FROM applications WHERE telegram_id = ? AND type = ? ORDER BY id DESC LIMIT 1", (telegram_id, app_type)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    time_diff = datetime.utcnow() - datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                    if time_diff < timedelta(hours=cooldown_hours):
                        return False, f"⏳ Подождите {int((timedelta(hours=cooldown_hours) - time_diff).total_seconds() // 60)} мин."
    return True, ""

async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id, roblox_username, display_name, roblox_id, position, career_status, telegram_username FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            return await cursor.fetchone()

async def find_user(query: str):
    if query.startswith("@"): query = query[1:]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id, roblox_username, display_name FROM users WHERE LOWER(roblox_username) = LOWER(?) OR LOWER(telegram_username) = LOWER(?)", (query, query)) as cursor:
            return await cursor.fetchone()

async def get_user_contracts(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT club_id, squad_type FROM contracts WHERE telegram_id = ?", (telegram_id,)) as cursor:
            return await cursor.fetchall()

async def save_user(telegram_id: int, username: str, user_id: int, display_name: str, tg_username: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO users (telegram_id, roblox_username, roblox_id, display_name, telegram_username) VALUES (?, ?, ?, ?, ?)", (telegram_id, username, user_id, display_name, tg_username))
        await db.commit()

async def update_user_field(telegram_id: int, field: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id))
        await db.commit()

async def create_application(telegram_id: int, app_type: str, text1: str, text2: str, text3: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO applications (telegram_id, type, text1, text2, text3, created_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)", (telegram_id, app_type, text1, text2, text3))
        await db.commit()
        return cursor.lastrowid

async def get_application(app_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id, type, text1, text2, text3 FROM applications WHERE id = ?", (app_id,)) as cursor:
            return await cursor.fetchone()

async def update_app_status(app_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE applications SET status = ? WHERE id = ?", (status, app_id))
        await db.commit()

async def get_user_applications(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, type, text1, status FROM applications WHERE telegram_id = ? ORDER BY id DESC LIMIT 10", (telegram_id,)) as cursor:
            return await cursor.fetchall()

async def get_setting(key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

# --- МЕНЮ ---
def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile"), InlineKeyboardButton(text="🛡 Мои клубы", callback_data="my_club")],
        [InlineKeyboardButton(text="🔍 Поиск клуба", callback_data="search_club"), InlineKeyboardButton(text="📝 Подать заявление", callback_data="application")],
        [InlineKeyboardButton(text="🏃‍♂️ Карьера", callback_data="career"), InlineKeyboardButton(text="📨 Мои заявки", callback_data="my_apps")],
        [InlineKeyboardButton(text="📢 Разместить объявление", callback_data="advertise")],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"), InlineKeyboardButton(text="ℹ️ Информация", callback_data="info")],
        [InlineKeyboardButton(text="📢 ТГ Трансфермаркета", url="https://t.me/TMRagdollSoccer")]
    ])

async def send_main_menu(message: Message, user_data: tuple = None):
    menu_text = "🏛 <b>Главное меню RGS | Transfer Market</b>\n\nВыберите раздел:"
    if user_data: menu_text = f"🏛 <b>Главное меню RGS</b>\n\nДобро пожаловать, <b>{user_data[2]}</b>!"
    await message.answer(menu_text, reply_markup=get_main_menu(), parse_mode="HTML")

# --- ОБРАБОТЧИКИ ---
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        await message.answer("👋 Перейдите в личные сообщения для регистрации.")
        return
    user_data = await get_user(message.from_user.id)
    if user_data:
        await state.clear()
        await send_main_menu(message, user_data)
    else:
        await message.answer("🏛 <b>Добро пожаловать!</b>\n\nУкажите ваш Roblox username:", parse_mode="HTML")
        await state.set_state(Form.waiting_for_roblox_nick)

@dp.message(Form.waiting_for_roblox_nick)
async def process_roblox_nick(message: Message, state: FSMContext):
    username = (message.text or "").strip()
    if not username or len(username) < 3 or len(username) > 20:
        return await message.answer("❌ Некорректный формат никнейма.")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://users.roblox.com/v1/usernames/users", json={"usernames": [username], "excludeBannedUsers": True}, timeout=10) as resp:
                data = await resp.json()
            if not data.get("data"): raise Exception("Не найден")
            user_info = data["data"][0]
            user_id = user_info["id"]
            display_name = user_info.get("displayName", username)
            avatar_url = "https://www.roblox.com/favicon.ico"
            async with session.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=420x420&format=Png&isCircular=false", timeout=10) as avatar_resp:
                if avatar_resp.status == 200:
                    avatar_data = await avatar_resp.json()
                    if avatar_data.get("data"): avatar_url = avatar_data["data"][0]["imageUrl"]
    except Exception:
        return await message.answer("❌ Аккаунт не найден.")
    await save_user(message.from_user.id, username, user_id, display_name, message.from_user.username)
    pos_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧤 Вратарь", callback_data="setpos_Вратарь"), InlineKeyboardButton(text="🛡️ Защитник", callback_data="setpos_Защитник")],
        [InlineKeyboardButton(text="🎯 Полузащитник", callback_data="setpos_Полузащитник"), InlineKeyboardButton(text="⚡ Нападающий", callback_data="setpos_Нападающий")]
    ])
    try:
        await message.answer_photo(photo=URLInputFile(avatar_url), caption=f"✅ <b>Аккаунт верифицирован!</b>\n👤 {username}\n\nВыберите позицию:", parse_mode="HTML", reply_markup=pos_kb)
    except Exception:
        await message.answer(f"✅ <b>Аккаунт верифицирован!</b>\n👤 {username}\n\nВыберите позицию:", parse_mode="HTML", reply_markup=pos_kb)
    await state.clear()

@dp.callback_query(F.data.startswith("setpos_"))
async def set_initial_position(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await update_user_field(callback.from_user.id, "position", callback.data.replace("setpos_", ""))
    user_data = await get_user(callback.from_user.id)
    try: await callback.message.delete()
    except: pass
    await send_main_menu(callback.message, user_data)

@dp.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    user_data = await get_user(callback.from_user.id)
    if not user_data: return
    tg_id, username, display_name, roblox_id, position, status, tg_username = user_data
    contracts = await get_user_contracts(tg_id)
    club_info = "\n⚽ <b>Статус:</b> Свободный агент 🌴" if not contracts else "\n⚽ <b>Мои клубы:</b>"
    if contracts:
        for c_id, s_type in contracts:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT name, owner_id FROM clubs WHERE id = ?", (c_id,)) as cursor:
                    club_data = await cursor.fetchone()
                    if club_data:
                        role = "👑" if club_data[1] == tg_id else ""
                        club_info += f"\n  • {club_data[0]} ({s_type}) {role}"
    text = f"👤 <b>Профиль</b>\n\n🔹 <b>Username:</b> <code>{username}</code>\n🏷 <b>Display:</b> {display_name}\n🆔 <b>ID:</b> <code>{roblox_id}</code>\n{POSITIONS.get(position, '')} <b>Позиция:</b> {position}\n🏃‍♂️ <b>Карьера:</b> {status}{club_info}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Roblox", url=f"https://www.roblox.com/users/{roblox_id}/profile")],
        [InlineKeyboardButton(text="✏️ Сменить ник", callback_data="change_nick"), InlineKeyboardButton(text="🔄 Сменить позицию", callback_data="change_pos")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")]
    ])
    await safe_edit_text(callback.message, text, reply_markup=kb)

@dp.callback_query(F.data == "change_nick")
async def cb_change_nick(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await safe_edit_text(callback.message, "Введите новый Roblox username:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="open_menu")]]))
    await state.set_state(Form.changing_nick)

@dp.message(Form.changing_nick, F.text)
async def process_nick_change(message: Message, state: FSMContext):
    new_nick = message.text.strip()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://users.roblox.com/v1/usernames/users", json={"usernames": [new_nick], "excludeBannedUsers": True}, timeout=10) as resp:
                data = await resp.json()
            if not data.get("data"): raise Exception("Не найден")
            new_id = data["data"][0]["id"]
    except Exception:
        return await message.answer("❌ Аккаунт не найден.")
    app_id = await create_application(message.from_user.id, "nick_change", new_nick, str(new_id), "none")
    await notify_admins(f"<b>Смена ника</b>\nID: {message.from_user.id}\nНовый: <code>{new_nick}</code>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_nick_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]]))
    await message.answer("⏳ Отправлено админам.")
    await state.clear()

@dp.callback_query(F.data == "change_pos")
async def cb_change_pos(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    pos_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧤 Вратарь", callback_data="setpos_Вратарь"), InlineKeyboardButton(text="🛡️ Защитник", callback_data="setpos_Защитник")],
        [InlineKeyboardButton(text="🎯 Полузащитник", callback_data="setpos_Полузащитник"), InlineKeyboardButton(text="⚡ Нападающий", callback_data="setpos_Нападающий")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile")]
    ])
    await safe_edit_text(callback.message, "Выберите новую позицию:", reply_markup=pos_kb)

@dp.callback_query(F.data == "my_club")
async def cb_my_club(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    user_data = await get_user(callback.from_user.id)
    if not user_data: return
    contracts = await get_user_contracts(user_data[0])
    if not contracts:
        return await safe_edit_text(callback.message, "🛡 <b>Мои клубы</b>\n\nВы Свободный агент 🌴.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")]]))
    kb_list = []
    for club_id, squad_type in contracts:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name, owner_id FROM clubs WHERE id = ?", (club_id,)) as cursor:
                club_data = await cursor.fetchone()
                if club_data:
                    btn_text = f"{'👑' if club_data[1] == user_data[0] else '🛡'} {club_data[0]} ({squad_type})"
                    kb_list.append([InlineKeyboardButton(text=btn_text, callback_data=f"manage_club_{club_id}")])
    kb_list.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")])
    await safe_edit_text(callback.message, "🛡 <b>Мои клубы</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("manage_club_"))
async def cb_manage_club(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    club_id = int(callback.data.split("_")[2])
    tg_id = callback.from_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, owner_id FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_data = await cursor.fetchone()
    if not club_data: return
    club_name, owner_id = club_data
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT squad_type FROM contracts WHERE telegram_id = ? AND club_id = ?", (tg_id, club_id)) as cursor:
            row = await cursor.fetchone()
    if not row: return
    squad_type = row[0]
    if owner_id == tg_id:
        text = f"🛡 <b>Управление: {club_name}</b>\nВаш статус: <b>{squad_type}</b>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Состав", callback_data=f"club_roster_{club_id}"), InlineKeyboardButton(text="🔍 Поиск игроков", callback_data=f"club_search_players_{club_id}")],
            [InlineKeyboardButton(text="📩 Пригласить", callback_data=f"club_invite_{club_id}"), InlineKeyboardButton(text="🗑 Кикнуть", callback_data=f"club_kick_{club_id}")],
            [InlineKeyboardButton(text="⚔️ Поиск товы", callback_data=f"club_friendly_{club_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_club")]
        ])
    else:
        text = f"🛡 <b>Клуб: {club_name}</b>\nВаш статус: <b>{squad_type}</b>"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👥 Состав", callback_data=f"club_roster_{club_id}")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_club")]])
    await safe_edit_text(callback.message, text, reply_markup=kb)

@dp.callback_query(F.data.startswith("club_roster_"))
async def cb_club_roster(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    club_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_name = (await cursor.fetchone())[0]
        async with db.execute("SELECT u.roblox_username, u.position, c.squad_type FROM contracts c JOIN users u ON c.telegram_id = u.telegram_id WHERE c.club_id = ?", (club_id,)) as cursor:
            players = await cursor.fetchall()
    text = f"👥 <b>Состав: {club_name}</b>\n\n"
    osnova = [p for p in players if p[2] == 'Основа']
    rezerv = [p for p in players if p[2] == 'Резерв']
    if osnova: text += "🟢 <b>Основа:</b>\n" + "".join([f"• <code>{p[0]}</code> — {POSITIONS.get(p[1], '')} {p[1]}\n" for p in osnova]) + "\n"
    if rezerv: text += "🟡 <b>Резерв:</b>\n" + "".join([f"• <code>{p[0]}</code> — {POSITIONS.get(p[1], '')} {p[1]}\n" for p in rezerv])
    if not osnova and not rezerv: text += "Пусто."
    await safe_edit_text(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"manage_club_{club_id}")]]))

@dp.callback_query(F.data.startswith("club_search_players_"))
async def cb_club_search_players(callback: CallbackQuery, state: FSMContext):
    club_id = int(callback.data.split("_")[3])
    can, msg = await check_limit(callback.from_user.id, "club_search", 2, 2)
    if not can: return await callback.answer(msg, show_alert=True)
    try: await callback.answer()
    except TelegramBadRequest: pass
    await state.update_data(active_club_id=club_id)
    await safe_edit_text(callback.message, "🔍 <b>Поиск игроков</b>\nШаг 1. Нужные позиции:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"manage_club_{club_id}")]]))
    await state.set_state(Form.club_search_positions)

@dp.message(Form.club_search_positions, F.text)
async def process_club_search_pos(message: Message, state: FSMContext):
    await state.update_data(needed_pos=message.text)
    await message.answer("Шаг 2. Требования:")
    await state.set_state(Form.club_search_requirements)

@dp.message(Form.club_search_requirements, F.text)
async def process_club_search_reqs(message: Message, state: FSMContext):
    data = await state.get_data()
    club_id = data.get('active_club_id')
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_name = (await cursor.fetchone())[0]
    app_id = await create_application(message.from_user.id, "club_search", data.get('needed_pos'), message.text, club_name)
    await notify_admins(f"🔍 <b>Поиск игроков</b>\nКлуб: {club_name}\nПозиции: {data.get('needed_pos')}\nТребования: {message.text}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_clubsearch_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]]))
    await message.answer("⏳ Отправлено.")
    await state.clear()

@dp.callback_query(F.data.startswith("club_invite_"))
async def cb_club_invite(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    club_id = int(callback.data.split("_")[2])
    await state.update_data(active_club_id=club_id)
    await safe_edit_text(callback.message, "📩 <b>Приглашение</b>\nВведите Roblox ник или @username:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"manage_club_{club_id}")]]))
    await state.set_state(Form.invite_player_target)

@dp.message(Form.invite_player_target, F.text)
async def process_invite_target(message: Message, state: FSMContext):
    club_id = (await state.get_data()).get('active_club_id')
    target = await find_user(message.text.strip())
    if not target: return await message.answer("❌ Игрок не найден.")
    target_tg_id, target_roblox, _ = target
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT squad_type FROM contracts WHERE telegram_id = ? AND club_id = ?", (target_tg_id, club_id)) as cursor:
            if await cursor.fetchone(): return await message.answer("❌ Игрок уже в клубе.")
    invite_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 В Основу", callback_data=f"inv_type_Основа_{message.from_user.id}_{target_tg_id}_{club_id}"), InlineKeyboardButton(text="🟡 В Резерв", callback_data=f"inv_type_Резерв_{message.from_user.id}_{target_tg_id}_{club_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"manage_club_{club_id}")]
    ])
    # ИСПРАВЛЕНО: нельзя редактировать сообщение пользователя, отправляем новое
    await message.answer(f"📩 <b>Игрок {target_roblox}</b>\nВ какой состав?", reply_markup=invite_kb, parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("inv_type_"))
async def cb_invite_type(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    _, _, squad_type, owner_id, target_id, club_id = callback.data.split("_")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_name = (await cursor.fetchone())[0]
    invite_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_inv_{owner_id}_{target_id}_{squad_type}_{club_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_inv_{target_id}")]])
    try:
        await bot.send_message(int(target_id), f"📩 <b>Предложение!</b>\nКлуб <b>{club_name}</b> приглашает вас в <b>{squad_type}</b>.", reply_markup=invite_kb, parse_mode="HTML")
        await safe_edit_text(callback.message, "✅ Приглашение отправлено.")
    except Exception:
        await safe_edit_text(callback.message, "❌ Ошибка отправки.")

@dp.callback_query(F.data.startswith("accept_inv_"))
async def cb_accept_invite(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    _, _, owner_id, target_id, squad_type, club_id = callback.data.split("_")
    app_id = await create_application(int(target_id), "player_transfer", owner_id, f"{target_id}_{squad_type}_{club_id}", "pending")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_name = (await cursor.fetchone())[0]
    await notify_admins(f"🔄 <b>Трансфер</b>\nИгрок: {target_id}\nКлуб: {club_name}\nСостав: {squad_type}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"approve_transfer_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]]))
    await safe_edit_text(callback.message, "⏳ Ожидайте подтверждения.")

@dp.callback_query(F.data.startswith("decline_inv_"))
async def cb_decline_invite(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await safe_edit_text(callback.message, "❌ Вы отклонили.")

@dp.callback_query(F.data.startswith("club_kick_"))
async def cb_club_kick(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    club_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT u.telegram_id, u.roblox_username, c.squad_type FROM contracts c JOIN users u ON c.telegram_id = u.telegram_id WHERE c.club_id = ?", (club_id,)) as cursor:
            players = await cursor.fetchall()
    if not players: return await safe_edit_text(callback.message, "В клубе нет игроков.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"manage_club_{club_id}")]]))
    kb = [[InlineKeyboardButton(text=f"❌ {p[1]} ({p[2]})", callback_data=f"kick_{p[0]}_{club_id}")] for p in players]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"manage_club_{club_id}")])
    await safe_edit_text(callback.message, "🗑 Выберите игрока:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("kick_"))
async def cb_kick_player(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    _, target_id, club_id = callback.data.split("_")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM contracts WHERE telegram_id = ? AND club_id = ?", (target_id, club_id))
        await db.commit()
    await safe_edit_text(callback.message, "✅ Игрок исключен.")

@dp.callback_query(F.data.startswith("club_friendly_"))
async def cb_club_friendly(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    club_id = int(callback.data.split("_")[2])
    await state.update_data(active_club_id=club_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="3x3", callback_data="friendly_fmt_3x3"), InlineKeyboardButton(text="4x4", callback_data="friendly_fmt_4x4")], [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"manage_club_{club_id}")]])
    await safe_edit_text(callback.message, "⚔️ Выберите формат:", reply_markup=kb)
    await state.set_state(Form.friendly_format)

@dp.callback_query(F.data.startswith("friendly_fmt_"), Form.friendly_format)
async def cb_friendly_format(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await state.update_data(fmt=callback.data.split("_")[2])
    club_id = (await state.get_data()).get('active_club_id')
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Сегодня", callback_data="friendly_time_Сегодня"), InlineKeyboardButton(text="Сейчас", callback_data="friendly_time_Сейчас")], [InlineKeyboardButton(text="В ближайшее время", callback_data="friendly_time_В ближайшее время")], [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"manage_club_{club_id}")]])
    await safe_edit_text(callback.message, "⚔️ Выберите время:", reply_markup=kb)
    await state.set_state(Form.friendly_time)

@dp.callback_query(F.data.startswith("friendly_time_"), Form.friendly_time)
async def cb_friendly_time(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    data = await state.get_data()
    club_id = data.get('active_club_id')
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_name = (await cursor.fetchone())[0]
    app_id = await create_application(callback.from_user.id, "friendly_match", data.get('fmt'), callback.data.replace("friendly_time_", ""), club_name)
    post_text = f"⚔️ <b>Поиск товы</b>\nКлуб: {club_name}\nФормат: {data.get('fmt')}\nВремя: {callback.data.replace('friendly_time_', '')}\nСвязь: @{callback.from_user.username}"
    await notify_admins(post_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_friendly_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]]))
    await safe_edit_text(callback.message, "⏳ Отправлено.")
    await state.clear()

@dp.callback_query(F.data == "search_club")
async def cb_search_club(callback: CallbackQuery, state: FSMContext):
    user = await get_user(callback.from_user.id)
    if not user or user[4] == 'Не выбрана':
        await callback.answer()
        return await callback.message.answer("❌ Сначала выберите позицию.")
    can, msg = await check_limit(callback.from_user.id, "free_agent", 2, 2)
    if not can: return await callback.answer(msg, show_alert=True)
    try: await callback.answer()
    except TelegramBadRequest: pass
    await safe_edit_text(callback.message, "🛡 <b>Свободный агент</b>\nНапишите требования:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="open_menu")]]))
    await state.set_state(Form.entering_requirements)

@dp.message(Form.entering_requirements, F.text)
async def process_requirements(message: Message, state: FSMContext):
    await state.update_data(requirements=message.text)
    await message.answer("Укажите контакт:")
    await state.set_state(Form.entering_contact)

@dp.message(Form.entering_contact, F.text)
async def process_contact(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    reqs = (await state.get_data()).get('requirements')
    app_id = await create_application(message.from_user.id, "free_agent", user[4], reqs, message.text)
    post_text = f"🏆 <b>Свободный агент</b>\nИгрок: {user[1]}\nПозиция: {user[4]}\nТребования: {reqs}\nСвязь: {message.text}"
    await notify_admins(post_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_agent_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]]))
    await message.answer("⏳ Отправлено.")
    await state.clear()

@dp.callback_query(F.data == "advertise")
async def cb_advertise(callback: CallbackQuery, state: FSMContext):
    can, msg = await check_limit(callback.from_user.id, "ad", 1, 0)
    if not can: return await callback.answer(msg, show_alert=True)
    try: await callback.answer()
    except TelegramBadRequest: pass
    await safe_edit_text(callback.message, "📢 <b>Объявление</b>\nШаг 1. Напишите текст:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="open_menu")]]))
    await state.set_state(Form.entering_ad_text)

@dp.message(Form.entering_ad_text, F.text)
async def process_ad_text(message: Message, state: FSMContext):
    await state.update_data(ad_text=message.text)
    await message.answer("Шаг 2. Ссылка на канал:")
    await state.set_state(Form.entering_ad_link)

@dp.message(Form.entering_ad_link, F.text)
async def process_ad_link(message: Message, state: FSMContext):
    ad_text = (await state.get_data()).get('ad_text')
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
    app_id = await create_application(message.from_user.id, "ad", ad_text, username, message.text)
    await notify_admins(f"{ad_text}\n\n🔗 Ссылка: {message.text}\n👤 {username}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_ad_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]]))
    await message.answer("⏳ Отправлено.")
    await state.clear()

@dp.callback_query(F.data == "career")
async def cb_career(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    user = await get_user(callback.from_user.id)
    if not user: return
    status = user[5]
    text = f"🏃‍♂️ <b>Карьера</b>\nСтатус: <b>{status}</b>"
    buttons = []
    if status == "Активна":
        buttons.append([InlineKeyboardButton(text="⏸ Пауза", callback_data="career_pause")])
        buttons.append([InlineKeyboardButton(text="🏁 Завершить", callback_data="career_finish")])
    elif status == "Приостановлена":
        buttons.append([InlineKeyboardButton(text="▶️ Возобновить", callback_data="career_resume")])
        buttons.append([InlineKeyboardButton(text="🏁 Завершить", callback_data="career_finish")])
    else:
        buttons.append([InlineKeyboardButton(text="▶️ Вернуть", callback_data="career_resume")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")])
    await safe_edit_text(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "career_pause")
async def cb_career_pause(callback: CallbackQuery):
    await update_user_field(callback.from_user.id, "career_status", "Приостановлена")
    await callback.answer("Пауза.", show_alert=True)
    await cb_career(callback)

@dp.callback_query(F.data == "career_resume")
async def cb_career_resume(callback: CallbackQuery):
    await update_user_field(callback.from_user.id, "career_status", "Активна")
    await callback.answer("Возобновлено.", show_alert=True)
    await cb_career(callback)

@dp.callback_query(F.data == "career_finish")
async def cb_career_finish(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await safe_edit_text(callback.message, "🏁 Причина завершения:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="career")]]))
    await state.set_state(Form.career_finish_reason)

@dp.message(Form.career_finish_reason, F.text)
async def process_career_finish(message: Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    app_id = await create_application(message.from_user.id, "career_finish", user[4], message.text, "none")
    await notify_admins(f"🏁 <b>Завершение карьеры</b>\nИгрок: {user[1]}\nПричина: {message.text}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_career_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]]))
    await message.answer("⏳ Отправлено.")
    await state.clear()

@dp.callback_query(F.data == "application")
async def cb_application(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛡 Заявление на клуб", callback_data="app_club")], [InlineKeyboardButton(text="👑 В администрацию", callback_data="app_admin")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")]])
    await safe_edit_text(callback.message, "📝 Выберите тип:", reply_markup=kb)

@dp.callback_query(F.data == "app_club")
async def cb_app_club(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await safe_edit_text(callback.message, "🛡 Введите название клуба:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="application")]]))
    await state.set_state(Form.club_app_name)

@dp.message(Form.club_app_name, F.text)
async def process_club_name(message: Message, state: FSMContext):
    await state.update_data(club_name=message.text)
    await message.answer("Отправьте логотип (фото):")
    await state.set_state(Form.club_app_logo)

@dp.message(Form.club_app_logo, F.photo)
async def process_club_logo(message: Message, state: FSMContext):
    club_name = (await state.get_data()).get('club_name')
    file_id = message.photo[-1].file_id
    user = await get_user(message.from_user.id)
    app_id = await create_application(message.from_user.id, "club_app", club_name, file_id, user[1])
    await notify_admins(f"🛡 <b>Заявка на клуб</b>\nНазвание: {club_name}\nОт: @{message.from_user.username}", photo=file_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_club_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]]))
    await message.answer("⏳ Отправлено.")
    await state.clear()

@dp.callback_query(F.data == "app_admin")
async def cb_app_admin(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    if await get_setting('admin_apps_open') != 'True': return await safe_edit_text(callback.message, "❌ Набор закрыт.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="application")]]))
    await safe_edit_text(callback.message, "👑 Введите должность:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="application")]]))
    await state.set_state(Form.admin_app_position)

@dp.message(Form.admin_app_position, F.text)
async def process_admin_pos(message: Message, state: FSMContext):
    await state.update_data(admin_pos=message.text)
    await message.answer("Опишите опыт:")
    await state.set_state(Form.admin_app_experience)

@dp.message(Form.admin_app_experience, F.text)
async def process_admin_exp(message: Message, state: FSMContext):
    data = await state.get_data()
    user = await get_user(message.from_user.id)
    app_id = await create_application(message.from_user.id, "admin_app", data.get('admin_pos'), message.text, user[1])
    await notify_admins(f"👑 <b>Заявка в админы</b>\nДолжность: {data.get('admin_pos')}\nОт: @{message.from_user.username}\nОпыт: {message.text}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_adminapp_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]]))
    await message.answer("⏳ Отправлено.")
    await state.clear()

@dp.callback_query(F.data == "my_apps")
async def cb_my_apps(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    apps = await get_user_applications(callback.from_user.id)
    text = "📨 <b>Мои заявки</b>\n\n" if apps else "📨 У вас нет заявок."
    for app in apps:
        status = "⏳ На рассмотрении" if app[3] == 'pending' else ("✅ Одобрено" if app[3] == 'approved' else "❌ Отклонено")
        text += f"🔹 <b>{APP_TYPES.get(app[1], 'Заявка')}</b> (ID: {app[0]})\n   Статус: {status}\n\n"
    await safe_edit_text(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")]]))

@dp.callback_query(F.data.startswith("approve_"), IsAdmin())
async def approve_app(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[-1])
    app_data = await get_application(app_id)
    if not app_data: return
    tg_id, app_type, text1, text2, text3 = app_data
    admin_name = callback.from_user.full_name
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest: pass

    if app_type == "club_app":
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("INSERT INTO clubs (name, logo_id, owner_id) VALUES (?, ?, ?)", (text1, text2, tg_id))
            await db.execute("INSERT INTO contracts (telegram_id, club_id, squad_type) VALUES (?, ?, 'Основа')", (tg_id, cursor.lastrowid))
            await db.commit()
        await bot.send_photo(CHANNEL_ID, photo=text2, caption=f"🛡 <b>Новый клуб</b>\n{text1}\nВладелец: {text3}", parse_mode="HTML")
        await bot.send_message(tg_id, "✅ Клуб одобрен!")
    elif app_type == "player_transfer":
        player_tg_id, squad_type, club_id = text2.split("_")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO contracts (telegram_id, club_id, squad_type) VALUES (?, ?, ?)", (int(player_tg_id), int(club_id), squad_type))
            async with db.execute("SELECT name FROM clubs WHERE id = ?", (int(club_id),)) as cursor:
                club_name = (await cursor.fetchone())[0]
            await db.commit()
        await bot.send_message(CHANNEL_ID, f"🔄 <b>Трансфер</b>\nИгрок перешел в {club_name}", parse_mode="HTML")
        await bot.send_message(int(player_tg_id), f"✅ Вы приняты в {club_name}!")
    elif app_type == "free_agent":
        await bot.send_message(CHANNEL_ID, f"🏆 <b>Свободный агент</b>\n{text1}\n{text2}\n{text3}", parse_mode="HTML")
    elif app_type == "friendly_match":
        await bot.send_message(CHANNEL_ID, f"⚔️ <b>Товарищеский матч</b>\n{text3}\n{text1}\n{text2}", parse_mode="HTML")
    elif app_type == "club_search":
        # ДОБАВЛЕНО: публикация поиска игроков
        await bot.send_message(CHANNEL_ID, f"🔍 <b>Поиск игроков</b>\nКлуб: {text3}\nПозиции: {text1}\nТребования: {text2}", parse_mode="HTML")
        await bot.send_message(tg_id, "✅ Ваш поиск игроков опубликован!")
    elif app_type == "admin_app":
        # ДОБАВЛЕНО: уведомление кандидату
        await bot.send_message(tg_id, f"✅ Ваша заявка в администрацию ({text1}) одобрена! Свяжитесь с владельцем.")
    elif app_type == "ad":
        await bot.send_message(CHANNEL_ID, f"{text1}\n\n🔗 {text3}\n👤 {text2}", parse_mode="HTML")
    elif app_type == "nick_change":
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET roblox_username = ?, roblox_id = ? WHERE telegram_id = ?", (text1, text2, tg_id))
            await db.commit()
        await bot.send_message(tg_id, f"✅ Ник изменен на {text1}!")
    elif app_type == "career_finish":
        await update_user_field(tg_id, "career_status", "Завершена")
        await bot.send_message(tg_id, "✅ Карьера завершена.")

    await update_app_status(app_id, "approved")
    await callback.message.reply(f"✅ Заявка #{app_id} одобрена админом {admin_name}.")

@dp.callback_query(F.data.startswith("reject_"), IsAdmin())
async def reject_app(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[-1])
    app_data = await get_application(app_id)
    if not app_data: return
    tg_id = app_data[0]
    admin_name = callback.from_user.full_name
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest: pass
    await update_app_status(app_id, "rejected")
    await callback.message.reply(f"❌ Заявка #{app_id} отклонена админом {admin_name}.")
    try: await bot.send_message(tg_id, "❌ Ваша заявка отклонена.")
    except: pass

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await is_admin(message.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")], [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")]])
    await message.answer("👑 <b>Админ-панель</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "admin_stats", IsAdmin())
async def admin_stats(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: u = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM clubs") as c2: c = (await c2.fetchone())[0]
    await safe_edit_text(callback.message, f"📊 <b>Статистика</b>\nИгроков: {u}\nКлубов: {c}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]]))

@dp.callback_query(F.data == "admin_settings", IsAdmin())
async def admin_settings(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    btn = "Закрыть заявки" if await get_setting('admin_apps_open') == 'True' else "Открыть заявки"
    await safe_edit_text(callback.message, "⚙️ Настройки", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn, callback_data="toggle_admin_apps")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]]))

@dp.callback_query(F.data == "toggle_admin_apps", IsAdmin())
async def cb_toggle_admin(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await set_setting('admin_apps_open', 'False' if await get_setting('admin_apps_open') == 'True' else 'True')
    await admin_settings(callback)

@dp.callback_query(F.data == "admin_back", IsAdmin())
async def admin_back(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await safe_edit_text(callback.message, "👑 <b>Админ-панель</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")], [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")]]))

@dp.callback_query(F.data == "open_menu")
async def cb_open_menu(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await state.clear()
    user = await get_user(callback.from_user.id)
    try: await callback.message.delete()
    except: pass
    await send_main_menu(callback.message, user)

@dp.callback_query(F.data == "info")
async def cb_info(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await safe_edit_text(callback.message, "🏛 <b>RGS Transfer Market</b>\nИщите клуб, собирайте команду, управляйте карьерой.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")]]))

@dp.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await safe_edit_text(callback.message, "🆘 Напишите ваш вопрос:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="open_menu")]]))
    await state.set_state(Form.entering_ticket_text)

@dp.message(Form.entering_ticket_text, F.text)
async def process_ticket_text(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO tickets (user_id, text) VALUES (?, ?)", (message.from_user.id, message.text))
        await db.commit()
    await notify_admins(f"🎫 <b>Тикет #{cursor.lastrowid}</b>\nОт: @{message.from_user.username}\n{message.text}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✍️ Ответить", callback_data=f"reply_ticket_{cursor.lastrowid}")]]))
    await message.answer("✅ Отправлено.")
    await state.clear()

@dp.callback_query(F.data.startswith("reply_ticket_"), IsAdmin())
async def cb_admin_reply_ticket(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await state.update_data(ticket_id=int(callback.data.split("_")[2]))
    await safe_edit_text(callback.message, "Напишите ответ:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_cancel_reply")]]))
    await state.set_state(Form.entering_ticket_reply)

@dp.message(Form.entering_ticket_reply, IsAdmin())
async def process_ticket_reply(message: Message, state: FSMContext):
    ticket_id = (await state.get_data()).get('ticket_id')
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, text FROM tickets WHERE id = ?", (ticket_id,)) as cursor:
            ticket = await cursor.fetchone()
    if ticket:
        try:
            await bot.send_message(ticket[0], f"🎫 <b>Ответ поддержки</b>\nВопрос: {ticket[1]}\nОтвет: {message.text}", parse_mode="HTML")
            await message.answer("✅ Отправлено.")
        except: pass
    await state.clear()

@dp.callback_query(F.data == "admin_cancel_reply", IsAdmin())
async def cb_admin_cancel_reply(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await state.clear()
    await safe_edit_text(callback.message, "❌ Отменено.")

@dp.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass

# --- ЗАПУСК ---
async def main():
    try:
        logger.info("⏳ Начинаю инициализацию БД...")
        await init_db()

        logger.info("⏳ Сбрасываю вебхук...")
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Вебхук сброшен.")

        logger.info("✅ Бот успешно запущен. Начинаю polling...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        # Ждем, чтобы хост не перезапускал бота по кругу
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
