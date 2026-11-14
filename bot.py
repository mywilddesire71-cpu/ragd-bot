import asyncio
import aiosqlite
import aiohttp
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, URLInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = "users.db"

OWNER_ID = 2046978907
CHANNEL_ID = "@TMRagdollSoccer"
ADMIN_CHAT_ID = -1004376666585

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

POSITIONS = {
    "Вратарь": "🧤",
    "Защитник": "🛡️",
    "Полузащитник": "🎯",
    "Нападающий": "⚡"
}

APP_TYPES = {
    "free_agent": "Свободный агент",
    "club_app": "Заявка на клуб",
    "admin_app": "Заявка в администрацию",
    "nick_change": "Смена ника",
    "career_finish": "Завершение карьеры",
    "player_transfer": "Трансфер игрока",
    "club_search": "Поиск игроков (Клуб)",
    "friendly_match": "Поиск товы",
    "ad": "Объявление / Реклама"
}

# --- ФИЛЬТР ДЛЯ ПРОВЕРКИ ПРАВ АДМИНА ---
class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return await is_admin(event.from_user.id)

# --- СОСТОЯНИЯ ---
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS clubs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                logo_id TEXT,
                owner_id INTEGER
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                roblox_username TEXT NOT NULL,
                roblox_id INTEGER,
                display_name TEXT,
                position TEXT DEFAULT 'Не выбрана',
                career_status TEXT DEFAULT 'Активна',
                club_id INTEGER DEFAULT NULL,
                is_owner INTEGER DEFAULT 0,
                telegram_username TEXT
            )
        """)
        try: await db.execute("ALTER TABLE users ADD COLUMN position TEXT DEFAULT 'Не выбрана'")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN career_status TEXT DEFAULT 'Активна'")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN club_id INTEGER DEFAULT NULL")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN is_owner INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN telegram_username TEXT")
        except aiosqlite.OperationalError: pass
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                type TEXT DEFAULT 'free_agent',
                text1 TEXT,
                text2 TEXT,
                text3 TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        try: await db.execute("ALTER TABLE applications ADD COLUMN created_at DATETIME")
        except aiosqlite.OperationalError: pass
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        try: await db.execute("INSERT INTO settings (key, value) VALUES ('admin_apps_open', 'True')")
        except aiosqlite.IntegrityError: pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                text TEXT,
                status TEXT DEFAULT 'open'
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                telegram_id INTEGER PRIMARY KEY,
                added_by INTEGER
            )
        """)

        await db.commit()

async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID: return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM admins WHERE telegram_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None

async def notify_admins(text: str, reply_markup=None, photo=None):
    try:
        if photo:
            await bot.send_photo(OWNER_ID, photo=photo, caption=text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await bot.send_message(OWNER_ID, text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        print(f"❌ [ОШИБКА] Не удалось отправить сообщение владельцу {OWNER_ID}: {e}")

    try:
        if photo:
            await bot.send_photo(ADMIN_CHAT_ID, photo=photo, caption=text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await bot.send_message(ADMIN_CHAT_ID, text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        print(f"❌ [ОШИБКА] Не удалось отправить сообщение в общий чат {ADMIN_CHAT_ID}: {e}")

async def check_limit(telegram_id: int, app_type: str, daily_limit: int, cooldown_hours: float) -> tuple[bool, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        if daily_limit > 0:
            async with db.execute(
                "SELECT COUNT(*) FROM applications WHERE telegram_id = ? AND type = ? AND date(created_at) = date('now')",
                (telegram_id, app_type)
            ) as cursor:
                count = (await cursor.fetchone())[0]
                if count >= daily_limit:
                    return False, f"❌ Вы достигли дневного лимита ({daily_limit} раз(а) в день) для этого действия. Попробуйте завтра."

        if cooldown_hours > 0:
            async with db.execute(
                "SELECT created_at FROM applications WHERE telegram_id = ? AND type = ? ORDER BY id DESC LIMIT 1",
                (telegram_id, app_type)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    last_time_str = row[0]
                    try:
                        last_time = datetime.strptime(last_time_str, "%Y-%m-%d %H:%M:%S")
                        now = datetime.utcnow()
                        time_diff = now - last_time
                        if time_diff < timedelta(hours=cooldown_hours):
                            remaining = timedelta(hours=cooldown_hours) - time_diff
                            minutes = int(remaining.total_seconds() // 60)
                            return False, f"⏳ Подождите, пожалуйста. Следующая попытка будет доступна через {minutes} мин."
                    except ValueError:
                        pass
    return True, ""

async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id, roblox_username, display_name, roblox_id, position, career_status, club_id, is_owner FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            return await cursor.fetchone()

async def find_user(query: str):
    if query.startswith("@"):
        query = query[1:]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id, roblox_username, display_name, club_id FROM users WHERE LOWER(roblox_username) = LOWER(?) OR LOWER(telegram_username) = LOWER(?)", (query, query)) as cursor:
            return await cursor.fetchone()

async def save_user(telegram_id: int, username: str, user_id: int, display_name: str, tg_username: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (telegram_id, roblox_username, roblox_id, display_name, telegram_username) VALUES (?, ?, ?, ?, ?)",
            (telegram_id, username, user_id, display_name, tg_username)
        )
        await db.commit()

async def update_user_field(telegram_id: int, field: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {field} = ? WHERE telegram_id = ?", (value, telegram_id))
        await db.commit()

async def create_application(telegram_id: int, app_type: str, text1: str, text2: str, text3: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO applications (telegram_id, type, text1, text2, text3, created_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (telegram_id, app_type, text1, text2, text3)
        )
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

# --- КОМАНДЫ ДЛЯ ГРУПП ---
@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📖 <b>Доступные команды:</b>\n\n"
        "👤 /profile [ник] — посмотреть свой профиль или профиль другого игрока\n"
        "🛡 /club — посмотреть состав своего клуба\n"
        "📩 /transfer [ник] — пригласить игрока в клуб (только для владельцев)\n"
        "ℹ️ /help — показать это сообщение\n\n"
        "🔍 <i>Вместо [ник] можно указать Roblox-ник или Telegram @username.</i>"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        user = await find_user(args[1])
        if not user:
            await message.answer("❌ Игрок с таким ником не найден.")
            return
        tg_id, roblox_name, display_name, club_id = user
    else:
        user = await get_user(message.from_user.id)
        if not user:
            await message.answer("❌ Вы еще не зарегистрированы. Напишите боту в личку /start.")
            return
        tg_id = user[0]
        roblox_name = user[1]
        display_name = user[2]
        club_id = user[6]
    
    club_info = ""
    if club_id:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name, owner_id FROM clubs WHERE id = ?", (club_id,)) as cursor:
                club = await cursor.fetchone()
                if club:
                    role = "Владелец" if club[1] == tg_id else "Игрок"
                    club_info = f"\n⚽ <b>Клуб:</b> {club[0]} ({role})"
    else:
        club_info = "\n⚽ <b>Клуб:</b> Свободный агент 🌴"
        
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT position, career_status FROM users WHERE telegram_id = ?", (tg_id,)) as cursor:
            pos_data = await cursor.fetchone()
            position = pos_data[0] if pos_data else "Не выбрана"
            status = pos_data[1] if pos_data else "Активна"
    
    emoji = POSITIONS.get(position, "❓")
    text = (
        f"👤 <b>Профиль:</b> <code>{roblox_name}</code>\n"
        f"🏷 <b>Display:</b> {display_name}\n"
        f"{emoji} <b>Позиция:</b> {position}\n"
        f"🏃‍♂️ <b>Карьера:</b> {status}"
        f"{club_info}"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("club"))
async def cmd_club(message: Message):
    user_data = await get_user(message.from_user.id)
    if not user_data:
        await message.answer("❌ Вы не зарегистрированы. Напишите боту в личку /start.")
        return
    club_id = user_data[6]
    if not club_id:
        await message.answer("❌ Вы не состоите в клубе. Вы свободный агент.")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_name = (await cursor.fetchone())[0]
        async with db.execute("SELECT roblox_username, position, is_owner FROM users WHERE club_id = ?", (club_id,)) as cursor:
            players = await cursor.fetchall()
    
    text = f"🛡 <b>Клуб: {club_name}</b>\n\n"
    for p in players:
        emoji = POSITIONS.get(p[1], "")
        role = "👑 (Владелец)" if p[2] else ""
        text += f"• <code>{p[0]}</code> — {emoji} {p[1]} {role}\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("transfer"))
async def cmd_transfer(message: Message):
    user_data = await get_user(message.from_user.id)
    if not user_data:
        await message.answer("❌ Вы не зарегистрированы. Напишите боту в личку /start.")
        return
    if not user_data[7]: 
        await message.answer("❌ Только владелец клуба может отправлять приглашения.")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: <code>/transfer @username</code> или <code>/transfer RobloxNick</code>", parse_mode="HTML")
        return
    
    target_query = args[1].strip()
    target = await find_user(target_query)
    
    if not target:
        await message.answer(f"❌ Игрок <b>{target_query}</b> не найден.", parse_mode="HTML")
        return
    
    target_tg_id, target_roblox, target_display, target_club_id = target
    
    if target_club_id is not None:
        await message.answer("❌ Этот игрок уже состоит в другом клубе.")
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (user_data[6],)) as cursor:
            club_name = (await cursor.fetchone())[0]
    
    invite_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_inv_{message.from_user.id}_{target_tg_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_inv_{target_tg_id}")]
    ])
    
    try:
        await bot.send_message(
            target_tg_id, 
            f"📩 <b>Вам поступило предложение!</b>\n\nКлуб <b>{club_name}</b> приглашает вас в состав.\n\nПринять предложение?", 
            parse_mode="HTML", 
            reply_markup=invite_kb
        )
        await message.answer(f"✅ Приглашение отправлено игроку <b>{target_roblox}</b>.", parse_mode="HTML")
    except Exception:
        await message.answer("❌ Не удалось отправить сообщение игроку. Возможно, он заблокировал бота.")

# --- МЕНЮ И РЕГИСТРАЦИЯ ---
def get_main_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile"), InlineKeyboardButton(text="🛡 Мой клуб", callback_data="my_club")],
        [
            InlineKeyboardButton(text="🔍 Поиск клуба", callback_data="search_club"),
            InlineKeyboardButton(text="📝 Подать заявление", callback_data="application")
        ],
        [
            InlineKeyboardButton(text="🏃‍♂️ Карьера", callback_data="career"),
            InlineKeyboardButton(text="📨 Мои заявки", callback_data="my_apps")
        ],
        [InlineKeyboardButton(text="📢 Разместить объявление", callback_data="advertise")],
        [
            InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"),
            InlineKeyboardButton(text="ℹ️ Информация", callback_data="info")
        ],
        [InlineKeyboardButton(text="📢 ТГ Трансфермаркета", url="https://t.me/TMRagdollSoccer")]
    ])
    return keyboard

async def send_main_menu(message: Message, user_data: tuple = None):
    menu_text = "🏛 <b>Главное меню RGS | Transfer Market</b>\n\nВыберите необходимый раздел для продолжения работы:"
    if user_data:
        menu_text = f"🏛 <b>Главное меню RGS | Transfer Market</b>\n\nДобро пожаловать, <b>{user_data[2]}</b>!\nВыберите необходимый раздел:"
    await message.answer(menu_text, reply_markup=get_main_menu(), parse_mode="HTML")

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        await message.answer("👋 Привет! Чтобы зарегистрироваться и пользоваться ботом, перейдите в личные сообщения: @RGS_TransferBot")
        return
    
    user_data = await get_user(message.from_user.id)
    if user_data:
        await state.clear()
        await send_main_menu(message, user_data)
    else:
        welcome_text = (
            "🏛 <b>Добро пожаловать в официальный бот RGS Transfer Market</b>\n\n"
            "Для получения доступа к функционалу трансферного рынка "
            "необходимо пройти верификацию Roblox-аккаунта.\n\n"
            "🔹 <b>Укажите ваш Roblox username (никнейм, не display name).</b>\n"
            "Пример: <code>RobloxPlayer123</code>"
        )
        await message.answer(welcome_text, parse_mode="HTML")
        await state.set_state(Form.waiting_for_roblox_nick)

@dp.message(Form.waiting_for_roblox_nick)
async def process_roblox_nick(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username or len(username) < 3 or len(username) > 20:
        await message.answer("❌ Некорректный формат никнейма. Попробуйте ещё раз.")
        return

    try:
        async with aiohttp.ClientSession() as session:
            api_url = "https://users.roblox.com/v1/usernames/users"
            payload = {"usernames": [username], "excludeBannedUsers": True}
            async with session.post(api_url, json=payload, timeout=10) as resp:
                data = await resp.json()
            if not data.get("data"): raise Exception("Не найден")
            user_info = data["data"][0]
            user_id = user_info["id"]
            display_name = user_info.get("displayName", username)
            
            avatar_url = "https://www.roblox.com/favicon.ico"
            avatar_api = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=420x420&format=Png&isCircular=false"
            async with session.get(avatar_api, timeout=10) as avatar_resp:
                if avatar_resp.status == 200:
                    avatar_data = await avatar_resp.json()
                    if avatar_data.get("data"):
                        avatar_url = avatar_data["data"][0]["imageUrl"]
    except Exception:
        await message.answer("❌ Аккаунт не найден. Проверьте написание.")
        return

    await save_user(message.from_user.id, username, user_id, display_name, message.from_user.username)
    
    pos_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧤 Вратарь", callback_data="setpos_Вратарь"), InlineKeyboardButton(text="🛡️ Защитник", callback_data="setpos_Защитник")],
        [InlineKeyboardButton(text="🎯 Полузащитник", callback_data="setpos_Полузащитник"), InlineKeyboardButton(text="⚡ Нападающий", callback_data="setpos_Нападающий")]
    ])
    await message.answer_photo(photo=URLInputFile(avatar_url), caption=f"✅ <b>Аккаунт верифицирован!</b>\n👤 {username}\n\nТеперь выберите вашу позицию на поле:", parse_mode="HTML", reply_markup=pos_kb)
    await state.clear()

@dp.callback_query(F.data.startswith("setpos_"))
async def set_initial_position(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    pos = callback.data.replace("setpos_", "")
    await update_user_field(callback.from_user.id, "position", pos)
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
    tg_id, username, display_name, roblox_id, position, status, club_id, is_owner = user_data
    emoji = POSITIONS.get(position, "❓")
    
    club_status = "Свободный агент 🌴"
    if club_id:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
                club_name = (await cursor.fetchone())[0]
                club_status = f"Владелец клуба {club_name} 👑" if is_owner else f"Игрок клуба {club_name} 🛡"

    profile_text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🔹 <b>Username:</b> <code>{username}</code>\n"
        f"🏷 <b>Display:</b> {display_name}\n"
        f"🆔 <b>ID:</b> <code>{roblox_id}</code>\n"
        f"{emoji} <b>Позиция:</b> {position}\n"
        f"🏃‍♂️ <b>Статус карьеры:</b> {status}\n"
        f"⚽ <b>Клубный статус:</b> {club_status}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть в Roblox", url=f"https://www.roblox.com/users/{roblox_id}/profile")],
        [InlineKeyboardButton(text="✏️ Сменить ник", callback_data="change_nick"), InlineKeyboardButton(text="🔄 Сменить позицию", callback_data="change_pos")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")]
    ])
    await callback.message.edit_text(profile_text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data == "change_nick")
async def cb_change_nick(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await callback.message.edit_text("Введите ваш новый Roblox username.\nОн будет отправлен на проверку администрации.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="open_menu")]]))
    await state.set_state(Form.changing_nick)

@dp.message(Form.changing_nick, F.text)
async def process_nick_change(message: Message, state: FSMContext):
    new_nick = message.text.strip()
    try:
        async with aiohttp.ClientSession() as session:
            api_url = "https://users.roblox.com/v1/usernames/users"
            payload = {"usernames": [new_nick], "excludeBannedUsers": True}
            async with session.post(api_url, json=payload, timeout=10) as resp:
                data = await resp.json()
            if not data.get("data"): raise Exception("Не найден")
            user_info = data["data"][0]
            new_id = user_info["id"]
    except Exception:
        await message.answer("❌ Аккаунт с таким ником не найден. Попробуйте снова или нажмите Отмену.")
        return

    app_id = await create_application(message.from_user.id, "nick_change", new_nick, str(new_id), "none")
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_nick_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]
    ])
    await message.answer("⏳ Запрос на смену ника отправлен администрации.")
    await notify_admins(f"<b>Запрос на смену ника</b>\nПользователь: {message.from_user.id}\nНовый ник: <code>{new_nick}</code> (ID: {new_id})", reply_markup=admin_kb)
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
    await callback.message.edit_text("Выберите новую позицию:", reply_markup=pos_kb)

@dp.callback_query(F.data == "my_club")
async def cb_my_club(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    user_data = await get_user(callback.from_user.id)
    if not user_data: return
    club_id, is_owner = user_data[6], user_data[7]

    if not club_id:
        text = "🛡 <b>Мой клуб</b>\n\nВы пока не состоите в клубе. Вы <b>Свободный агент</b>.\nПодайте заявление на создание клуба или ждите приглашения."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")]])
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_name = (await cursor.fetchone())[0]

    if is_owner:
        text = f"🛡 <b>Управление клубом: {club_name}</b>\n\nВы владелец этого клуба. Выберите действие:"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Состав", callback_data="club_roster"), InlineKeyboardButton(text="🔍 Поиск игроков", callback_data="club_search_players")],
            [InlineKeyboardButton(text="📩 Пригласить игрока", callback_data="club_invite"), InlineKeyboardButton(text="🗑 Кикнуть игрока", callback_data="club_kick")],
            [InlineKeyboardButton(text="⚔️ Поиск товы", callback_data="club_friendly")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")]
        ])
    else:
        text = f"🛡 <b>Мой клуб: {club_name}</b>\n\nВы являетесь игроком этого клуба."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Состав команды", callback_data="club_roster")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")]
        ])
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "club_roster")
async def cb_club_roster(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    user_data = await get_user(callback.from_user.id)
    club_id = user_data[6]
    if not club_id: return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT roblox_username, position, is_owner FROM users WHERE club_id = ?", (club_id,)) as cursor:
            players = await cursor.fetchall()

    text = "👥 <b>Состав команды</b>\n\n"
    for p in players:
        emoji = POSITIONS.get(p[1], "")
        role = "👑 (Владелец)" if p[2] else ""
        text += f"• <code>{p[0]}</code> — {emoji} {p[1]} {role}\n"
        
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_club")]])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "club_search_players")
async def cb_club_search_players(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    
    can_proceed, error_msg = await check_limit(callback.from_user.id, "club_search", daily_limit=2, cooldown_hours=2)
    if not can_proceed:
        try: await callback.answer(error_msg, show_alert=True)
        except TelegramBadRequest: pass
        return

    await callback.message.edit_text(
        "🔍 <b>Поиск игроков</b>\n\nШаг 1 из 2. Напишите, какие позиции вам нужны (например: Нападающий, Защитник):", 
        parse_mode="HTML", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="my_club")]])
    )
    await state.set_state(Form.club_search_positions)

@dp.message(Form.club_search_positions, F.text)
async def process_club_search_pos(message: Message, state: FSMContext):
    await state.update_data(needed_pos=message.text)
    await message.answer("Шаг 2 из 2. Напишите ваши <b>требования</b> к игрокам (например: опыт от 100 часов, онлайн каждый день):", parse_mode="HTML")
    await state.set_state(Form.club_search_requirements)

@dp.message(Form.club_search_requirements, F.text)
async def process_club_search_reqs(message: Message, state: FSMContext):
    data = await state.get_data()
    needed_pos = data.get('needed_pos')
    reqs = message.text
    
    user_data = await get_user(message.from_user.id)
    club_id = user_data[6]
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_name = (await cursor.fetchone())[0]
            
    app_id = await create_application(message.from_user.id, "club_search", needed_pos, reqs, club_name)
    
    admin_text = (
        f"🔍 <b>Заявка на поиск игроков</b>\n\n"
        f"🛡 <b>Клуб:</b> {club_name}\n"
        f"👤 <b>Владелец:</b> <code>{user_data[1]}</code>\n"
        f"🎯 <b>Нужные позиции:</b> {needed_pos}\n"
        f"📋 <b>Требования:</b>\n<i>{reqs}</i>"
    )
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_clubsearch_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]
    ])
    
    await message.answer("⏳ Заявка на поиск игроков отправлена на проверку администрации.")
    await notify_admins(admin_text, reply_markup=admin_kb)
    await state.clear()

@dp.callback_query(F.data == "club_invite")
async def cb_club_invite(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await callback.message.edit_text("📩 <b>Приглашение игрока</b>\n\nВведите Roblox ник или @username игрока:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="my_club")]]))
    await state.set_state(Form.invite_player_target)

@dp.message(Form.invite_player_target, F.text)
async def process_invite_target(message: Message, state: FSMContext):
    target_query = message.text.strip()
    target = await find_user(target_query)
    
    if not target:
        await message.answer(f"❌ Игрок <b>{target_query}</b> не найден в системе.", parse_mode="HTML")
        return
    
    target_tg_id, target_roblox, target_display, target_club_id = target
    
    if target_club_id is not None:
        await message.answer("❌ Этот игрок уже состоит в другом клубе.")
        return

    owner_data = await get_user(message.from_user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (owner_data[6],)) as cursor:
            club_name = (await cursor.fetchone())[0]

    invite_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept_inv_{message.from_user.id}_{target_tg_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"decline_inv_{target_tg_id}")]
    ])
    
    try:
        await bot.send_message(target_tg_id, f"📩 <b>Вам поступило предложение!</b>\n\nКлуб <b>{club_name}</b> приглашает вас в состав.\n\nПринять предложение?", parse_mode="HTML", reply_markup=invite_kb)
        await message.answer(f"✅ Приглашение отправлено игроку <b>{target_roblox}</b>.", parse_mode="HTML")
    except Exception:
        await message.answer("❌ Не удалось отправить сообщение игроку. Возможно, он заблокировал бота.")
        
    await state.clear()

@dp.callback_query(F.data.startswith("accept_inv_"))
async def cb_accept_invite(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    _, _, owner_tg_id, player_tg_id = callback.data.split("_")
    
    app_id = await create_application(int(player_tg_id), "player_transfer", owner_tg_id, player_tg_id, "pending_transfer")
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить трансфер", callback_data=f"approve_transfer_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]
    ])
    
    owner_data = await get_user(int(owner_tg_id))
    player_data = await get_user(int(player_tg_id))
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (owner_data[6],)) as cursor:
            club_name = (await cursor.fetchone())[0]

    await notify_admins(f"🔄 <b>Запрос на трансфер</b>\n\n👤 Игрок: <code>{player_data[1]}</code>\n🛡 Клуб: {club_name}\n\nОдобрить переход?", reply_markup=admin_kb)
    await callback.message.edit_text("⏳ Вы приняли приглашение. Ожидайте подтверждения от администрации.")

@dp.callback_query(F.data.startswith("decline_inv_"))
async def cb_decline_invite(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await callback.message.edit_text("❌ Вы отклонили приглашение клуба.")

@dp.callback_query(F.data == "club_kick")
async def cb_club_kick(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    user_data = await get_user(callback.from_user.id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id, roblox_username FROM users WHERE club_id = ? AND is_owner = 0", (user_data[6],)) as cursor:
            players = await cursor.fetchall()

    if not players:
        await callback.message.edit_text("В вашем клубе нет игроков.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_club")]]))
        return

    kb = []
    for p in players:
        kb.append([InlineKeyboardButton(text=f"❌ {p[1]}", callback_data=f"kick_{p[0]}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="my_club")])
    
    await callback.message.edit_text("🗑 Выберите игрока для исключения:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("kick_"))
async def cb_kick_player(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    target_tg_id = int(callback.data.split("_")[1])
    await update_user_field(target_tg_id, "club_id", None)
    await callback.message.edit_text("✅ Игрок исключен из клуба.")
    try:
        await bot.send_message(target_tg_id, "❌ Вас исключили из клуба. Теперь вы снова Свободный агент.")
    except: pass

@dp.callback_query(F.data == "club_friendly")
async def cb_club_friendly(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3x3", callback_data="friendly_fmt_3x3"), InlineKeyboardButton(text="4x4", callback_data="friendly_fmt_4x4")],
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="my_club")]
    ])
    await callback.message.edit_text("⚔️ <b>Поиск товы</b>\n\nШаг 1 из 2. Выберите формат матча:", parse_mode="HTML", reply_markup=kb)
    await state.set_state(Form.friendly_format)

@dp.callback_query(F.data.startswith("friendly_fmt_"), Form.friendly_format)
async def cb_friendly_format(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    fmt = callback.data.split("_")[2]
    await state.update_data(fmt=fmt)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сегодня", callback_data="friendly_time_Сегодня"), InlineKeyboardButton(text="Сейчас", callback_data="friendly_time_Сейчас")],
        [InlineKeyboardButton(text="В ближайшее время", callback_data="friendly_time_В ближайшее время")],
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="my_club")]
    ])
    await callback.message.edit_text("⚔️ <b>Поиск товы</b>\n\nШаг 2 из 2. Выберите время:", parse_mode="HTML", reply_markup=kb)
    await state.set_state(Form.friendly_time)

@dp.callback_query(F.data.startswith("friendly_time_"), Form.friendly_time)
async def cb_friendly_time(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    time_str = callback.data.replace("friendly_time_", "")
    data = await state.get_data()
    fmt = data.get('fmt')
    
    user_data = await get_user(callback.from_user.id)
    club_id = user_data[6]
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_name = (await cursor.fetchone())[0]

    username = f"@{callback.from_user.username}" if callback.from_user.username else f"ID: {callback.from_user.id}"
    
    app_id = await create_application(callback.from_user.id, "friendly_match", fmt, time_str, f"{club_name} | {username}")
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_friendly_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]
    ])
    
    post_text = (
        f"⚔️ ｜ <b>ПОИСК ТОВАРИЩЕСКОГО МАТЧА</b>\n\n"
        f"🛡 <b>Клуб:</b> {club_name}\n"
        f"👥 <b>Формат:</b> {fmt}\n"
        f"⏱ <b>Время:</b> {time_str}\n\n"
        f"📬 <b>Связь:</b> {username}"
    )
    
    await callback.message.edit_text("⏳ Заявка на поиск товы отправлена на проверку администрации.")
    await notify_admins(f"<b>Заявка на поиск товы (ID: {app_id})</b>\n\n{post_text}", reply_markup=admin_kb)
    await state.clear()

@dp.callback_query(F.data == "advertise")
async def cb_advertise(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    
    can_proceed, error_msg = await check_limit(callback.from_user.id, "ad", daily_limit=1, cooldown_hours=0)
    if not can_proceed:
        try: await callback.answer(error_msg, show_alert=True)
        except TelegramBadRequest: pass
        return

    await callback.message.edit_text(
        "📢 <b>Размещение объявления</b>\n\n"
        "Шаг 1 из 2. Напишите текст, который хотите опубликовать в канале (реклама канала, новостника и т.д.):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="open_menu")]])
    )
    await state.set_state(Form.entering_ad_text)

@dp.message(Form.entering_ad_text, F.text)
async def process_ad_text(message: Message, state: FSMContext):
    await state.update_data(ad_text=message.text)
    await message.answer(
        "Шаг 2 из 2. Укажите <b>ссылку на ваш канал</b> или ресурс (например: <code>https://t.me/your_channel</code>):",
        parse_mode="HTML"
    )
    await state.set_state(Form.entering_ad_link)

@dp.message(Form.entering_ad_link, F.text)
async def process_ad_link(message: Message, state: FSMContext):
    ad_link = message.text.strip()
    data = await state.get_data()
    ad_text = data.get('ad_text')
    
    username = f"@{message.from_user.username}" if message.from_user.username else f"ID: {message.from_user.id}"
    
    app_id = await create_application(message.from_user.id, "ad", ad_text, username, ad_link)
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_ad_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]
    ])
    
    check_text = f"{ad_text}\n\n🔗 <b>Ссылка:</b> {ad_link}\n👤 <b>Публиковал:</b> {username}"
    
    await message.answer("⏳ Ваше объявление отправлено на проверку администрации.")
    await notify_admins(f"<b>Новое объявление (ID: {app_id})</b>\n\n{check_text}", reply_markup=admin_kb)
    await state.clear()

@dp.callback_query(F.data == "search_club")
async def cb_search_club(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    user_data = await get_user(callback.from_user.id)
    if not user_data or user_data[4] == 'Не выбрана':
        await callback.message.answer("❌ Сначала выберите позицию в профиле.")
        return

    can_proceed, error_msg = await check_limit(callback.from_user.id, "free_agent", daily_limit=2, cooldown_hours=2)
    if not can_proceed:
        try: await callback.answer(error_msg, show_alert=True)
        except TelegramBadRequest: pass
        return

    await callback.message.edit_text("🛡 <b>Создание объявления: Свободный агент</b>\n\nНапишите ваши <b>требования</b>:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="open_menu")]]))
    await state.set_state(Form.entering_requirements)

@dp.message(Form.entering_requirements, F.text)
async def process_requirements(message: Message, state: FSMContext):
    await state.update_data(requirements=message.text)
    await message.answer("Укажите ваш <b>контакт для связи</b>:", parse_mode="HTML")
    await state.set_state(Form.entering_contact)

@dp.message(Form.entering_contact, F.text)
async def process_contact(message: Message, state: FSMContext):
    contact = message.text
    data = await state.get_data()
    requirements = data.get('requirements')
    
    user_data = await get_user(message.from_user.id)
    roblox_name, position = user_data[1], user_data[4]
    emoji = POSITIONS.get(position, "")
    
    app_id = await create_application(message.from_user.id, "free_agent", position, requirements, contact)
    post_text = f"🏆 ｜ <b>СВОБОДНЫЙ АГЕНТ</b>\n\n👤 <b>Игрок:</b> <code>{roblox_name}</code>\n{emoji} <b>Позиция:</b> {position}\n\n📋 <b>Требования:</b>\n<i>{requirements}</i>\n\n📬 <b>Связь:</b> {contact}"
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_agent_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]
    ])
    await message.answer("⏳ Ваше объявление отправлено на проверку администрации.")
    await notify_admins(f"<b>Новая заявка (ID: {app_id})</b>\n\n{post_text}", reply_markup=admin_kb)
    await state.clear()

@dp.callback_query(F.data == "career")
async def cb_career(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    user_data = await get_user(callback.from_user.id)
    if not user_data: return
    status = user_data[5]
    text = f"🏃‍♂️ <b>Управление карьерой</b>\n\nТекущий статус: <b>{status}</b>\n\nВыберите действие:"
    buttons = []
    if status == "Активна":
        buttons.append([InlineKeyboardButton(text="⏸ Приостановить", callback_data="career_pause")])
        buttons.append([InlineKeyboardButton(text="🏁 Завершить карьеру", callback_data="career_finish")])
    elif status == "Приостановлена":
        buttons.append([InlineKeyboardButton(text="▶️ Возобновить", callback_data="career_resume")])
        buttons.append([InlineKeyboardButton(text="🏁 Завершить карьеру", callback_data="career_finish")])
    elif status == "Завершена":
        text = "🏃‍♂️ <b>Управление карьерой</b>\n\nВаша карьера <b>завершена</b>."
        buttons.append([InlineKeyboardButton(text="▶️ Вернуть карьеру", callback_data="career_resume")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="open_menu")])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "career_pause")
async def cb_career_pause(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await update_user_field(callback.from_user.id, "career_status", "Приостановлена")
    try: await callback.answer("Карьера приостановлена.", show_alert=True)
    except TelegramBadRequest: pass
    await cb_career(callback)

@dp.callback_query(F.data == "career_resume")
async def cb_career_resume(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await update_user_field(callback.from_user.id, "career_status", "Активна")
    try: await callback.answer("Карьера возобновлена.", show_alert=True)
    except TelegramBadRequest: pass
    await cb_career(callback)

@dp.callback_query(F.data == "career_finish")
async def cb_career_finish(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await callback.message.edit_text("🏁 <b>Завершение карьеры</b>\n\nНапишите причину завершения карьеры:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="career")]]))
    await state.set_state(Form.career_finish_reason)

@dp.message(Form.career_finish_reason, F.text)
async def process_career_finish(message: Message, state: FSMContext):
    reason = message.text
    user_data = await get_user(message.from_user.id)
    app_id = await create_application(message.from_user.id, "career_finish", user_data[4], reason, "none")
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_career_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]
    ])
    await message.answer("⏳ Запрос на завершение карьеры отправлен администрации.")
    await notify_admins(f"<b>Завершение карьеры</b>\nОт: {user_data[1]}\nПричина:\n{reason}", reply_markup=admin_kb)
    await state.clear()

@dp.callback_query(F.data == "application")
async def cb_application(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡 Заявление на клуб", callback_data="app_club")],
        [InlineKeyboardButton(text="👑 Заявление в администрацию", callback_data="app_admin")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu")]
    ])
    await callback.message.edit_text("📝 <b>Подать заявление</b>\n\nВыберите тип заявления:", parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "app_club")
async def cb_app_club(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await callback.message.edit_text("🛡 <b>Заявление на клуб</b>\n\nШаг 1 из 2. Введите название вашего клуба:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="application")]]))
    await state.set_state(Form.club_app_name)

@dp.message(Form.club_app_name, F.text)
async def process_club_name(message: Message, state: FSMContext):
    await state.update_data(club_name=message.text)
    await message.answer("Шаг 2 из 2. Отправьте <b>логотип</b> вашего клуба (как фото):", parse_mode="HTML")
    await state.set_state(Form.club_app_logo)

@dp.message(Form.club_app_logo, F.photo)
async def process_club_logo(message: Message, state: FSMContext):
    data = await state.get_data()
    club_name = data.get('club_name')
    file_id = message.photo[-1].file_id
    user_data = await get_user(message.from_user.id)
    
    app_id = await create_application(message.from_user.id, "club_app", club_name, file_id, user_data[1])
    
    caption = f"🛡 <b>Новая заявка на клуб</b>\n\n🏷 <b>Название:</b> {club_name}\n👤 <b>От:</b> @{message.from_user.username}\n🎮 <b>Roblox:</b> {user_data[1]}"
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_club_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]
    ])
    
    await message.answer("⏳ Заявление на клуб отправлено на проверку.")
    await notify_admins(caption, photo=file_id, reply_markup=admin_kb)
    await state.clear()

@dp.callback_query(F.data == "app_admin")
async def cb_app_admin(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    is_open = await get_setting('admin_apps_open')
    if is_open != 'True':
        await callback.message.edit_text("❌ На данный момент набор в администрацию <b>закрыт</b>.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="application")]]))
        return
        
    await callback.message.edit_text("👑 <b>Заявление в администрацию</b>\n\nШаг 1 из 2. На какую <b>должность</b> вы претендуете?:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="application")]]))
    await state.set_state(Form.admin_app_position)

@dp.message(Form.admin_app_position, F.text)
async def process_admin_pos(message: Message, state: FSMContext):
    await state.update_data(admin_pos=message.text)
    await message.answer("Шаг 2 из 2. Опишите ваш <b>опыт</b> и расскажите о себе:", parse_mode="HTML")
    await state.set_state(Form.admin_app_experience)

@dp.message(Form.admin_app_experience, F.text)
async def process_admin_exp(message: Message, state: FSMContext):
    data = await state.get_data()
    admin_pos = data.get('admin_pos')
    experience = message.text
    user_data = await get_user(message.from_user.id)
    
    app_id = await create_application(message.from_user.id, "admin_app", admin_pos, experience, user_data[1])
    
    text = f"👑 <b>Заявка в администрацию</b>\n\n💼 <b>Должность:</b> {admin_pos}\n👤 <b>От:</b> @{message.from_user.username}\n🎮 <b>Roblox:</b> {user_data[1]}\n\n📝 <b>Опыт:</b>\n<i>{experience}</i>"
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_adminapp_{app_id}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}")]
    ])
    
    await message.answer("⏳ Заявление в администрацию отправлено на проверку.")
    await notify_admins(text, reply_markup=admin_kb)
    await state.clear()

@dp.callback_query(F.data == "my_apps")
async def cb_my_apps(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    apps = await get_user_applications(callback.from_user.id)
    if not apps:
        text = "📨 <b>Мои заявки</b>\n\nУ вас пока нет отправленных заявок."
    else:
        text = "📨 <b>Мои заявки (последние 10)</b>\n\n"
        for app in apps:
            app_id, app_type, text1, status = app
            type_name = APP_TYPES.get(app_type, "Заявка")
            status_icon = "⏳ На рассмотрении" if status == 'pending' else ("✅ Одобрено" if status == 'approved' else "❌ Отклонено")
            text += f"🔹 <b>{type_name}</b> (ID: {app_id})\n"
            if app_type in ["free_agent", "career_finish"]: text += f"   Позиция: {text1}\n"
            elif app_type in ["club_app", "admin_app", "club_search", "friendly_match"]: text += f"   Детали: {text1}\n"
            elif app_type == "ad": text += f"   Текст: {text1[:20]}...\n"
            text += f"   Статус: {status_icon}\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="open_menu")]])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

# ================= АДМИН ПАНЕЛЬ =================

async def show_admin_manage_admins(target):
    text = "👑 <b>Управление администраторами</b>\n\n"
    text += f"👤 Владелец: <code>{OWNER_ID}</code> (нельзя удалить)\n\n"
    
    kb = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id FROM admins") as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                kb.append([InlineKeyboardButton(text=f"❌ Удалить админа {r[0]}", callback_data=f"admin_remove_{r[0]}")])
    
    kb.append([InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=markup)

async def show_admin_club_info(target, club_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, owner_id FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club = await cursor.fetchone()
            
    if not club:
        if isinstance(target, CallbackQuery):
            try: await target.answer("Клуб не найден.", show_alert=True)
            except TelegramBadRequest: pass
        else:
            await target.answer("Клуб не найден.")
        return
        
    name, owner_id = club
    text = f"🛡 <b>Управление клубом</b>\n\n🏷 <b>Название:</b> {name}\n👑 <b>ID Владельца:</b> <code>{owner_id}</code>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"admin_rename_{club_id}")],
        [InlineKeyboardButton(text="🗑 Удалить клуб", callback_data=f"admin_delclub_{club_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manage_clubs")]
    ])
    
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await is_admin(message.from_user.id): return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👑 Управление админами", callback_data="admin_manage_admins")],
        [InlineKeyboardButton(text="🛡 Управление клубами", callback_data="admin_manage_clubs")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")]
    ])
    await message.answer("👑 <b>Админ-панель RGS</b>\n\nДобро пожаловать в панель управления. Выберите раздел:", parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "admin_stats", IsAdmin())
async def admin_stats(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c1: users_count = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM clubs") as c2: clubs_count = (await c2.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM applications WHERE status='pending'") as c3: apps_pending = (await c3.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM tickets WHERE status='open'") as c4: tickets_open = (await c4.fetchone())[0]

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего игроков: <code>{users_count}</code>\n"
        f"🛡 Всего клубов: <code>{clubs_count}</code>\n"
        f"⏳ Заявок на модерации: <code>{apps_pending}</code>\n"
        f"🎫 Открытых тикетов: <code>{tickets_open}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "admin_settings", IsAdmin())
async def admin_settings(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    is_open = await get_setting('admin_apps_open')
    status_text = "🟢 ОТКРЫТЫ" if is_open == 'True' else "🔴 ЗАКРЫТЫ"
    btn_text = "Закрыть заявки" if is_open == 'True' else "Открыть заявки"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Заявки в админы: {status_text}", callback_data="noop")],
        [InlineKeyboardButton(text=f"⚙️ {btn_text}", callback_data="toggle_admin_apps")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text("⚙️ <b>Настройки бота</b>", parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "toggle_admin_apps", IsAdmin())
async def cb_toggle_admin(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    is_open = await get_setting('admin_apps_open')
    new_val = 'False' if is_open == 'True' else 'True'
    await set_setting('admin_apps_open', new_val)
    await admin_settings(callback)

@dp.callback_query(F.data == "admin_manage_admins", IsAdmin())
async def admin_manage_admins(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await show_admin_manage_admins(callback)

@dp.callback_query(F.data == "admin_add", IsAdmin())
async def admin_add(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await callback.message.edit_text(
        "Отправьте <b>Telegram ID</b> пользователя, которого хотите назначить админом.\n\n"
        "<i>(Узнать ID можно у бота @userinfobot)</i>", 
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_manage_admins")]])
    )
    await state.set_state(Form.entering_new_admin_id)

@dp.message(Form.entering_new_admin_id, IsAdmin())
async def process_new_admin(message: Message, state: FSMContext):
    try:
        new_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ ID должен быть числом. Попробуйте снова.")
        return
        
    if new_id == OWNER_ID:
        await message.answer("❌ Этот пользователь уже является владельцем.")
        return
        
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO admins (telegram_id, added_by) VALUES (?, ?)", (new_id, message.from_user.id))
            await db.commit()
            await message.answer(f"✅ Пользователь <code>{new_id}</code> успешно назначен администратором!", parse_mode="HTML")
        except aiosqlite.IntegrityError:
            await message.answer("❌ Этот пользователь уже является администратором.")
            
    await state.clear()
    await show_admin_manage_admins(message)

@dp.callback_query(F.data.startswith("admin_remove_"), IsAdmin())
async def admin_remove(callback: CallbackQuery):
    target_id = int(callback.data.split("_")[2])
    try: await callback.answer(f"✅ Админ {target_id} удален.", show_alert=True)
    except TelegramBadRequest: pass
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE telegram_id = ?", (target_id,))
        await db.commit()
        
    await show_admin_manage_admins(callback)

@dp.callback_query(F.data == "admin_manage_clubs", IsAdmin())
async def admin_manage_clubs(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name FROM clubs LIMIT 15") as cursor:
            clubs = await cursor.fetchall()
            
    if not clubs:
        text = "🛡 <b>Управление клубами</b>\n\nКлубов пока нет."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]])
    else:
        text = "🛡 <b>Управление клубами</b>\n\nВыберите клуб для управления:"
        kb_list = []
        for c in clubs:
            kb_list.append([InlineKeyboardButton(text=f"⚙️ {c[1]}", callback_data=f"admin_club_{c[0]}")])
        kb_list.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_list)
        
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("admin_club_"), IsAdmin())
async def admin_club_info(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    club_id = int(callback.data.split("_")[2])
    await show_admin_club_info(callback, club_id)

@dp.callback_query(F.data.startswith("admin_rename_"), IsAdmin())
async def admin_rename_club(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    club_id = int(callback.data.split("_")[2])
    await state.update_data(rename_club_id=club_id)
    
    await callback.message.edit_text("Напишите новое название для этого клуба:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"admin_club_{club_id}")]]))
    await state.set_state(Form.entering_rename_club)

@dp.message(Form.entering_rename_club, IsAdmin())
async def process_rename_club(message: Message, state: FSMContext):
    data = await state.get_data()
    club_id = data.get('rename_club_id')
    new_name = message.text.strip()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE clubs SET name = ? WHERE id = ?", (new_name, club_id))
        await db.commit()
        
    await message.answer(f"✅ Клуб успешно переименован в <b>{new_name}</b>!", parse_mode="HTML")
    await state.clear()
    await show_admin_club_info(message, club_id)

@dp.callback_query(F.data.startswith("admin_delclub_"), IsAdmin())
async def admin_delclub(callback: CallbackQuery):
    club_id = int(callback.data.split("_")[2])
    try: await callback.answer("Удаление...", show_alert=True)
    except TelegramBadRequest: pass
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET club_id = NULL, is_owner = 0 WHERE club_id = ?", (club_id,))
        await db.execute("DELETE FROM clubs WHERE id = ?", (club_id,))
        await db.commit()
        
    await callback.message.edit_text("✅ Клуб успешно удален. Все игроки стали свободными агентами.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manage_clubs")]]))

@dp.callback_query(F.data == "admin_back", IsAdmin())
async def admin_back(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👑 Управление админами", callback_data="admin_manage_admins")],
        [InlineKeyboardButton(text="🛡 Управление клубами", callback_data="admin_manage_clubs")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")]
    ])
    await callback.message.edit_text("👑 <b>Админ-панель RGS</b>\n\nДобро пожаловать в панель управления. Выберите раздел:", parse_mode="HTML", reply_markup=kb)

# --- МОДЕРАЦИЯ ЗАЯВОК (С ОТВЕТОМ КТО СДЕЛАЛ) ---
@dp.callback_query(F.data.startswith("approve_agent_"), IsAdmin())
async def approve_agent(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[2])
    app_data = await get_application(app_id)
    tg_id, _, position, requirements, contact = app_data
    user_data = await get_user(tg_id)
    emoji = POSITIONS.get(position, "")
    post_text = f"🏆 ｜ <b>СВОБОДНЫЙ АГЕНТ</b>\n\n👤 <b>Игрок:</b> <code>{user_data[1]}</code>\n{emoji} <b>Позиция:</b> {position}\n\n📋 <b>Требования:</b>\n<i>{requirements}</i>\n\n📬 <b>Связь:</b> {contact}"
    try:
        await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
        await update_app_status(app_id, "approved")
        
        # Убираем кнопки
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest: pass
        
        admin_name = callback.from_user.full_name
        await callback.message.reply(f"✅ Заявка #{app_id} одобрена администратором {admin_name}.")
        
        await bot.send_message(tg_id, "✅ Ваше объявление (Свободный агент) одобрено!")
    except Exception as e:
        try: await callback.message.reply(f"⚠️ Ошибка: {e}")
        except: pass

@dp.callback_query(F.data.startswith("approve_club_"), IsAdmin())
async def approve_club(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[2])
    app_data = await get_application(app_id)
    tg_id, _, club_name, file_id, roblox_name = app_data
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO clubs (name, logo_id, owner_id) VALUES (?, ?, ?)", (club_name, file_id, tg_id))
        club_id = cursor.lastrowid
        await db.execute("UPDATE users SET club_id = ?, is_owner = 1 WHERE telegram_id = ?", (club_id, tg_id))
        await db.commit()

    post_text = f"🛡 ｜ <b>НОВЫЙ КЛУБ</b>\n\n🏷 <b>Название:</b> {club_name}\n👤 <b>Владелец:</b> <code>{roblox_name}</code>"
    try:
        await bot.send_photo(CHANNEL_ID, photo=file_id, caption=post_text, parse_mode="HTML")
        await update_app_status(app_id, "approved")
        
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest: pass
        
        admin_name = callback.from_user.full_name
        await callback.message.reply(f"✅ Заявка на клуб #{app_id} одобрена администратором {admin_name}.")
        
        await bot.send_message(tg_id, "✅ Ваше заявление на клуб одобрено! Вам доступен раздел 'Мой клуб'.")
    except Exception as e:
        try: await callback.message.reply(f"⚠️ Ошибка при публикации: {e}")
        except: pass

@dp.callback_query(F.data.startswith("approve_clubsearch_"), IsAdmin())
async def approve_clubsearch(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[2])
    app_data = await get_application(app_id)
    tg_id, _, needed_pos, reqs, club_name = app_data
    user_data = await get_user(tg_id)
    
    post_text = (
        f"🔍 ｜ <b>ПОИСК ИГРОКОВ</b>\n\n"
        f"🛡 <b>Клуб:</b> {club_name}\n"
        f"🎯 <b>Нужные позиции:</b> {needed_pos}\n\n"
        f"📋 <b>Требования:</b>\n"
        f"<i>{reqs}</i>\n\n"
        f"📬 <b>Связь:</b> @{user_data[2]}"
    )
    
    try:
        await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
        await update_app_status(app_id, "approved")
        
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest: pass
        
        admin_name = callback.from_user.full_name
        await callback.message.reply(f"✅ Заявка на поиск #{app_id} одобрена администратором {admin_name}.")
        
        await bot.send_message(tg_id, "✅ Ваше объявление о поиске игроков одобрено и опубликовано в канале!")
    except Exception as e:
        try: await callback.message.reply(f"⚠️ Ошибка: {e}")
        except: pass

@dp.callback_query(F.data.startswith("approve_adminapp_"), IsAdmin())
async def approve_adminapp(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[2])
    app_data = await get_application(app_id)
    tg_id = app_data[0]
    await update_app_status(app_id, "approved")
    
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest: pass
    
    admin_name = callback.from_user.full_name
    await callback.message.reply(f"✅ Заявка в администрацию #{app_id} одобрена администратором {admin_name}.")
    
    await bot.send_message(tg_id, "✅ Ваша заявка в администрацию одобрена! С вами свяжутся.")

@dp.callback_query(F.data.startswith("approve_nick_"), IsAdmin())
async def approve_nick(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[2])
    app_data = await get_application(app_id)
    tg_id, _, new_nick, new_id, _ = app_data
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET roblox_username = ?, roblox_id = ? WHERE telegram_id = ?", (new_nick, new_id, tg_id))
        await db.commit()
    await update_app_status(app_id, "approved")
    
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest: pass
    
    admin_name = callback.from_user.full_name
    await callback.message.reply(f"✅ Смена ника на {new_nick} (#{app_id}) одобрена администратором {admin_name}.")
    
    await bot.send_message(tg_id, f"✅ Ваш новый ник <code>{new_nick}</code> одобрен!", parse_mode="HTML")

@dp.callback_query(F.data.startswith("approve_career_"), IsAdmin())
async def approve_career(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[2])
    app_data = await get_application(app_id)
    tg_id, _, position, reason, _ = app_data
    user_data = await get_user(tg_id)
    emoji = POSITIONS.get(position, "")
    post_text = f"🏁 ｜ <b>ЗАВЕРШЕНИЕ КАРЬЕРЫ</b>\n\n👤 <b>Игрок:</b> <code>{user_data[1]}</code>\n{emoji} <b>Позиция:</b> {position}\n\n📝 <b>Сообщение:</b>\n<i>{reason}</i>"
    await update_user_field(tg_id, "career_status", "Завершена")
    await update_app_status(app_id, "approved")
    try:
        await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
        
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest: pass
        
        admin_name = callback.from_user.full_name
        await callback.message.reply(f"✅ Завершение карьеры #{app_id} одобрено администратором {admin_name}.")
        
        await bot.send_message(tg_id, "✅ Ваша карьера официально завершена.")
    except Exception as e:
        try: await callback.message.reply(f"⚠️ Ошибка: {e}")
        except: pass

@dp.callback_query(F.data.startswith("approve_friendly_"), IsAdmin())
async def approve_friendly(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[2])
    app_data = await get_application(app_id)
    tg_id, _, fmt, time_str, club_and_username = app_data
    
    try:
        club_name, username = club_and_username.split(" | ")
    except ValueError:
        club_name = club_and_username
        username = "Не указана"
    
    post_text = (
        f"⚔️ ｜ <b>ПОИСК ТОВАРИЩЕСКОГО МАТЧА</b>\n\n"
        f"🛡 <b>Клуб:</b> {club_name}\n"
        f"👥 <b>Формат:</b> {fmt}\n"
        f"⏱ <b>Время:</b> {time_str}\n\n"
        f"📬 <b>Связь:</b> {username}"
    )
    
    try:
        await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
        await update_app_status(app_id, "approved")
        
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest: pass
        
        admin_name = callback.from_user.full_name
        await callback.message.reply(f"✅ Заявка на поиск товы #{app_id} одобрена администратором {admin_name}.")
        
        await bot.send_message(tg_id, "✅ Ваше объявление о поиске товы одобрено и опубликовано в канале!")
    except Exception as e:
        try: await callback.message.reply(f"⚠️ Ошибка: {e}")
        except: pass

@dp.callback_query(F.data.startswith("approve_ad_"), IsAdmin())
async def approve_ad(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[2])
    app_data = await get_application(app_id)
    tg_id, _, ad_text, username, ad_link = app_data

    post_text = f"{ad_text}\n\n🔗 <b>Ссылка:</b> {ad_link}\n👤 <b>Публиковал:</b> {username}"
    
    try:
        await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
        await update_app_status(app_id, "approved")
        
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest: pass
        
        admin_name = callback.from_user.full_name
        await callback.message.reply(f"✅ Объявление #{app_id} одобрено администратором {admin_name}.")
        
        await bot.send_message(tg_id, "✅ Ваше объявление одобрено и опубликовано в канале!")
    except Exception as e:
        try: await callback.message.reply(f"⚠️ Ошибка: {e}")
        except: pass

@dp.callback_query(F.data.startswith("approve_transfer_"), IsAdmin())
async def cb_approve_transfer(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    app_id = int(callback.data.split("_")[2])
    app_data = await get_application(app_id)
    _, _, owner_tg_id, player_tg_id, _ = app_data
    
    owner_data = await get_user(int(owner_tg_id))
    player_data = await get_user(int(player_tg_id))
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (owner_data[6],)) as cursor:
            club_name = (await cursor.fetchone())[0]
        await db.execute("UPDATE users SET club_id = ? WHERE telegram_id = ?", (owner_data[6], player_tg_id))
        await db.commit()
        
    await update_app_status(app_id, "approved")
    
    post_text = f"🔄 ｜ <b>ТРАНСФЕР ЗАВЕРШЕН</b>\n\n👤 <b>Игрок:</b> <code>{player_data[1]}</code>\n🛡 <b>Новый клуб:</b> {club_name}"
    try:
        await bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
        
        try: await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest: pass
        
        admin_name = callback.from_user.full_name
        await callback.message.reply(f"✅ Трансфер #{app_id} одобрен администратором {admin_name}.")
        
        await bot.send_message(int(player_tg_id), f"✅ Ваш переход в клуб <b>{club_name}</b> одобрен!", parse_mode="HTML")
        await bot.send_message(int(owner_tg_id), f"✅ Игрок <code>{player_data[1]}</code> успешно принят в ваш клуб!", parse_mode="HTML")
    except Exception as e:
        try: await callback.message.reply(f"⚠️ Ошибка: {e}")
        except: pass

@dp.callback_query(F.data.startswith("reject_"), IsAdmin())
async def reject_app(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    
    parts = callback.data.split("_")
    app_id = int(parts[-1])
    app_data = await get_application(app_id)
    
    if not app_data:
        return
        
    tg_id = app_data[0]
    app_type = app_data[1]
    
    await update_app_status(app_id, "rejected")
    
    try: await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest: pass
    
    admin_name = callback.from_user.full_name
    try:
        await callback.message.reply(f"❌ Заявка #{app_id} отклонена администратором {admin_name}.")
    except TelegramBadRequest:
        pass
        
    try:
        await bot.send_message(tg_id, "❌ К сожалению, ваша заявка была отклонена.")
    except Exception:
        pass

@dp.callback_query(F.data == "info")
async def cb_info(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    info_text = (
        "🏛 <b>О платформе RGS Transfer Market</b>\n\n"
        "Добро пожаловать в официальный бот трансферного рынка RGS. Здесь вы можете найти клуб, собрать свою команду или управлять карьерой.\n\n"
        "📌 <b>Основные возможности:</b>\n"
        "👤 <b>Профиль</b> — ваша карточка игрока, смена ника и позиции.\n"
        "🛡 <b>Мой клуб</b> — управление составом (доступно только владельцам).\n"
        "🔍 <b>Поиск клуба</b> — подать анкету Свободного агента.\n"
        "📝 <b>Подать заявление</b> — создание клуба или заявка в администрацию.\n"
        "🏃‍♂️ <b>Карьера</b> — приостановка или завершение карьеры.\n\n"
        "⚙️ <b>Как это работает?</b>\n"
        "1. Вы регистрируетесь и получаете статус <b>Свободного агента</b>.\n"
        "2. Подаете заявку на создание клуба (или вас приглашает другой клуб).\n"
        "3. Все трансферы и объявления проходят проверку администрацией и публикуются в официальном канале.\n\n"
        "⚠️ <b>Правила:</b>\n"
        "— Запрещен спам и фейковые заявки.\n"
        "— Уважайте других игроков и администрацию.\n\n"
        "📢 <b>Наш канал:</b> @TMRagdollSoccer"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Перейти в канал", url="https://t.me/TMRagdollSoccer")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="open_menu")]
    ])
    await callback.message.edit_text(info_text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)

@dp.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    support_text = (
        "🆘 <b>Служба поддержки</b>\n\n"
        "Если у вас возникли технические проблемы, ошибка при верификации или вопросы по работе трансферного рынка, вы можете создать обращение (тикет).\n"
        "Администрация ответит вам в ближайшее время прямо в этом чате.\n\n"
        "👑 <b>Владелец:</b> @v7vvv7vvv7vvv"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать в поддержку", callback_data="create_ticket")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="open_menu")]
    ])
    await callback.message.edit_text(support_text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "create_ticket")
async def cb_create_ticket(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await callback.message.edit_text(
        "✍️ <b>Напишите ваш вопрос или описание проблемы</b> одним сообщением.\nМы передадим его администрации.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="support")]])
    )
    await state.set_state(Form.entering_ticket_text)

@dp.message(Form.entering_ticket_text, F.text)
async def process_ticket_text(message: Message, state: FSMContext):
    ticket_text = message.text
    user_data = await get_user(message.from_user.id)
    roblox_name = user_data[1] if user_data else "Неизвестно"

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO tickets (user_id, text) VALUES (?, ?)", (message.from_user.id, ticket_text))
        ticket_id = cursor.lastrowid
        await db.commit()

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"reply_ticket_{ticket_id}")]
    ])

    await notify_admins(
        f"🎫 <b>Новый тикет #{ticket_id}</b>\n\n👤 <b>От:</b> @{message.from_user.username} ({message.from_user.id})\n🎮 <b>Roblox:</b> {roblox_name}\n\n📝 <b>Проблема:</b>\n<i>{ticket_text}</i>",
        reply_markup=admin_kb
    )
    await message.answer("✅ Ваше обращение отправлено в поддержку. Ожидайте ответа.")
    await state.clear()

@dp.callback_query(F.data.startswith("reply_ticket_"), IsAdmin())
async def cb_admin_reply_ticket(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    ticket_id = int(callback.data.split("_")[2])
    
    await state.update_data(ticket_id=ticket_id)
    await callback.message.edit_text(f"✍️ <b>Ответ на тикет #{ticket_id}</b>\n\nНапишите текст ответа для пользователя:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_cancel_reply")]]))
    await state.set_state(Form.entering_ticket_reply)

@dp.message(Form.entering_ticket_reply, IsAdmin())
async def process_ticket_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get('ticket_id')
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, text FROM tickets WHERE id = ?", (ticket_id,)) as cursor:
            ticket = await cursor.fetchone()
            
    if not ticket:
        await message.answer("❌ Тикет не найден.")
        await state.clear()
        return
        
    user_id, original_text = ticket
    
    try:
        await bot.send_message(
            user_id,
            f"🎫 <b>Ответ поддержки по тикету #{ticket_id}</b>\n\n<b>Ваш вопрос:</b>\n<i>{original_text}</i>\n\n<b>Ответ:</b>\n{message.text}",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Ответ успешно отправлен пользователю.")
    except Exception as e:
        await message.answer(f"⚠️ Ошибка отправки: {e}. Возможно, пользователь заблокировал бота.")
        
    await state.clear()

@dp.callback_query(F.data == "admin_cancel_reply", IsAdmin())
async def cb_admin_cancel_reply(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await state.clear()
    await callback.message.edit_text("❌ Ответ отменен.")

@dp.callback_query(F.data == "open_menu")
async def cb_open_menu(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await state.clear()
    user_data = await get_user(callback.from_user.id)
    try: await callback.message.delete()
    except: pass
    await send_main_menu(callback.message, user_data)

@dp.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass

# --- ЗАПУСК ---
async def main():
    await init_db()
    print("Бот успешно запущен!")
    
    try:
        await bot.send_message(CHANNEL_ID, "🚀 <b>Бот успешно перезапущен и готов к работе!</b>", parse_mode="HTML")
    except Exception as e:
        print(f"Не удалось отправить уведомление в канал: {e}")

    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
