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
from aiogram.enums import ButtonStyle

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

# --- БЕЗОПАСНОЕ РЕДАКТИРОВАНИЕ ---
async def safe_edit_text(message: Message, text: str, reply_markup=None, parse_mode="HTML"):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        pass

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
                telegram_username TEXT
            )
        """)
        try: await db.execute("ALTER TABLE users ADD COLUMN position TEXT DEFAULT 'Не выбрана'")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN career_status TEXT DEFAULT 'Активна'")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN telegram_username TEXT")
        except aiosqlite.OperationalError: pass

        # ТАБЛИЦА КОНТРАКТОВ (ПОЗВОЛЯЕТ ИГРОКУ БЫТЬ В 2-Х КЛУБАХ)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                club_id INTEGER,
                squad_type TEXT DEFAULT 'Основа',
                UNIQUE(telegram_id, club_id)
            )
        """)

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
        async with db.execute("SELECT telegram_id, roblox_username, display_name, roblox_id, position, career_status, telegram_username FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            return await cursor.fetchone()

async def find_user(query: str):
    if query.startswith("@"):
        query = query[1:]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id, roblox_username, display_name FROM users WHERE LOWER(roblox_username) = LOWER(?) OR LOWER(telegram_username) = LOWER(?)", (query, query)) as cursor:
            return await cursor.fetchone()

async def get_user_contracts(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT club_id, squad_type FROM contracts WHERE telegram_id = ?", (telegram_id,)) as cursor:
            return await cursor.fetchall()

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

# --- МЕНЮ ---
def get_main_menu():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile", style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(text="🛡 Мои клубы", callback_data="my_club", style=ButtonStyle.PRIMARY)
        ],
        [
            InlineKeyboardButton(text="🔍 Поиск клуба", callback_data="search_club", style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="📝 Подать заявление", callback_data="application", style=ButtonStyle.SUCCESS)
        ],
        [
            InlineKeyboardButton(text="🏃‍♂️ Карьера", callback_data="career", style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(text="📨 Мои заявки", callback_data="my_apps", style=ButtonStyle.PRIMARY)
        ],
        [InlineKeyboardButton(text="📢 Разместить объявление", callback_data="advertise", style=ButtonStyle.SUCCESS)],
        [
            InlineKeyboardButton(text="🆘 Поддержка", callback_data="support", style=ButtonStyle.DANGER),
            InlineKeyboardButton(text="ℹ️ Информация", callback_data="info", style=ButtonStyle.PRIMARY)
        ],
        [InlineKeyboardButton(text="📢 ТГ Трансфермаркета", url="https://t.me/TMRagdollSoccer", style=ButtonStyle.PRIMARY)]
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
        [InlineKeyboardButton(text="🧤 Вратарь", callback_data="setpos_Вратарь", style=ButtonStyle.PRIMARY), InlineKeyboardButton(text="🛡️ Защитник", callback_data="setpos_Защитник", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton(text="🎯 Полузащитник", callback_data="setpos_Полузащитник", style=ButtonStyle.PRIMARY), InlineKeyboardButton(text="⚡ Нападающий", callback_data="setpos_Нападающий", style=ButtonStyle.PRIMARY)]
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

# --- ПРОФИЛЬ (С 2 КЛУБАМИ) ---
@dp.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    user_data = await get_user(callback.from_user.id)
    if not user_data: return
    tg_id, username, display_name, roblox_id, position, status, tg_username = user_data
    emoji = POSITIONS.get(position, "❓")
    
    contracts = await get_user_contracts(tg_id)
    
    club_info = ""
    if not contracts:
        club_info = "\n⚽ <b>Клубный статус:</b> Свободный агент 🌴"
    else:
        club_info = "\n⚽ <b>Мои клубы:</b>"
        for c_id, s_type in contracts:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT name, owner_id FROM clubs WHERE id = ?", (c_id,)) as cursor:
                    club_data = await cursor.fetchone()
                    if club_data:
                        role = "👑 (Владелец)" if club_data[1] == tg_id else ""
                        club_info += f"\n  • {club_data[0]} ({s_type}) {role}"

    profile_text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🔹 <b>Username:</b> <code>{username}</code>\n"
        f"🏷 <b>Display:</b> {display_name}\n"
        f"🆔 <b>ID:</b> <code>{roblox_id}</code>\n"
        f"{emoji} <b>Позиция:</b> {position}\n"
        f"🏃‍♂️ <b>Статус карьеры:</b> {status}"
        f"{club_info}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Открыть в Roblox", url=f"https://www.roblox.com/users/{roblox_id}/profile", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton(text="✏️ Сменить ник", callback_data="change_nick", style=ButtonStyle.SUCCESS), InlineKeyboardButton(text="🔄 Сменить позицию", callback_data="change_pos", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu", style=ButtonStyle.DANGER)]
    ])
    await safe_edit_text(callback.message, profile_text, reply_markup=keyboard)

@dp.callback_query(F.data == "change_nick")
async def cb_change_nick(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    await safe_edit_text(callback.message, "Введите ваш новый Roblox username.\nОн будет отправлен на проверку администрации.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data="open_menu", style=ButtonStyle.DANGER)]]))
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
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_nick_{app_id}", style=ButtonStyle.SUCCESS), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{app_id}", style=ButtonStyle.DANGER)]
    ])
    await message.answer("⏳ Запрос на смену ника отправлен администрации.")
    await notify_admins(f"<b>Запрос на смену ника</b>\nПользователь: {message.from_user.id}\nНовый ник: <code>{new_nick}</code> (ID: {new_id})", reply_markup=admin_kb)
    await state.clear()

@dp.callback_query(F.data == "change_pos")
async def cb_change_pos(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    pos_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧤 Вратарь", callback_data="setpos_Вратарь", style=ButtonStyle.PRIMARY), InlineKeyboardButton(text="🛡️ Защитник", callback_data="setpos_Защитник", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton(text="🎯 Полузащитник", callback_data="setpos_Полузащитник", style=ButtonStyle.PRIMARY), InlineKeyboardButton(text="⚡ Нападающий", callback_data="setpos_Нападающий", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile", style=ButtonStyle.DANGER)]
    ])
    await safe_edit_text(callback.message, "Выберите новую позицию:", reply_markup=pos_kb)

# --- МОИ КЛУБЫ ---
@dp.callback_query(F.data == "my_club")
async def cb_my_club(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    user_data = await get_user(callback.from_user.id)
    if not user_data: return
    tg_id = user_data[0]
    
    contracts = await get_user_contracts(tg_id)
    
    if not contracts:
        text = "🛡 <b>Мои клубы</b>\n\nВы пока не состоите ни в одном клубе. Вы <b>Свободный агент</b>.\nПодайте заявление на создание клуба или ждите приглашения."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu", style=ButtonStyle.DANGER)]])
        await safe_edit_text(callback.message, text, reply_markup=kb)
        return

    text = "🛡 <b>Мои клубы</b>\n\nВыберите клуб для управления:"
    kb_list = []
    
    for club_id, squad_type in contracts:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name, owner_id FROM clubs WHERE id = ?", (club_id,)) as cursor:
                club_data = await cursor.fetchone()
                if club_data:
                    is_owner = club_data[1] == tg_id
                    btn_text = f"{'👑' if is_owner else '🛡'} {club_data[0]} ({squad_type})"
                    kb_list.append([InlineKeyboardButton(text=btn_text, callback_data=f"manage_club_{club_id}", style=ButtonStyle.PRIMARY)])
    
    kb_list.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="open_menu", style=ButtonStyle.DANGER)])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_list)
    
    await safe_edit_text(callback.message, text, reply_markup=kb)

@dp.callback_query(F.data.startswith("manage_club_"))
async def cb_manage_club(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    club_id = int(callback.data.split("_")[2])
    tg_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, owner_id FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_data = await cursor.fetchone()
            
    if not club_data:
        await callback.answer("Клуб не найден.", show_alert=True)
        return
        
    club_name, owner_id = club_data
    is_owner = owner_id == tg_id
    
    # Получаем тип контракта (Основа/Резерв)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT squad_type FROM contracts WHERE telegram_id = ? AND club_id = ?", (tg_id, club_id)) as cursor:
            squad_type = (await cursor.fetchone())[0]

    if is_owner:
        text = f"🛡 <b>Управление клубом: {club_name}</b>\n\nВы владелец этого клуба.\nВаш статус в клубе: <b>{squad_type}</b>\nВыберите действие:"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Состав", callback_data=f"club_roster_{club_id}", style=ButtonStyle.PRIMARY), InlineKeyboardButton(text="🔍 Поиск игроков", callback_data=f"club_search_players_{club_id}", style=ButtonStyle.SUCCESS)],
            [InlineKeyboardButton(text="📩 Пригласить игрока", callback_data=f"club_invite_{club_id}", style=ButtonStyle.SUCCESS), InlineKeyboardButton(text="🗑 Кикнуть игрока", callback_data=f"club_kick_{club_id}", style=ButtonStyle.DANGER)],
            [InlineKeyboardButton(text="⚔️ Поиск товы", callback_data=f"club_friendly_{club_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_club", style=ButtonStyle.DANGER)]
        ])
    else:
        text = f"🛡 <b>Клуб: {club_name}</b>\n\nВы являетесь игроком этого клуба.\nВаш статус: <b>{squad_type}</b>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Состав команды", callback_data=f"club_roster_{club_id}", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_club", style=ButtonStyle.DANGER)]
        ])
    
    await safe_edit_text(callback.message, text, reply_markup=kb)

@dp.callback_query(F.data.startswith("club_roster_"))
async def cb_club_roster(callback: CallbackQuery):
    try: await callback.answer()
    except TelegramBadRequest: pass
    club_id = int(callback.data.split("_")[2])
    tg_id = callback.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем имя клуба
        async with db.execute("SELECT name FROM clubs WHERE id = ?", (club_id,)) as cursor:
            club_name = (await cursor.fetchone())[0]
        
        # Получаем игроков из таблицы контрактов
        async with db.execute("""
            SELECT u.roblox_username, u.position, c.squad_type, u.telegram_id 
            FROM contracts c 
            JOIN users u ON c.telegram_id = u.telegram_id 
            WHERE c.club_id = ?
        """, (club_id,)) as cursor:
            players = await cursor.fetchall()

    text = f"👥 <b>Состав команды: {club_name}</b>\n\n"
    osnova = [p for p in players if p[2] == 'Основа']
    rezerv = [p for p in players if p[2] == 'Резерв']
    
    if osnova:
        text += "🟢 <b>Основа:</b>\n"
        for p in osnova:
            emoji = POSITIONS.get(p[1], "")
            role = "👑" if p[3] == tg_id else ""
            text += f"• <code>{p[0]}</code> — {emoji} {p[1]} {role}\n"
        text += "\n"
    
    if rezerv:
        text += "🟡 <b>Резерв:</b>\n"
        for p in rezerv:
            emoji = POSITIONS.get(p[1], "")
            role = "👑" if p[3] == tg_id else ""
            text += f"• <code>{p[0]}</code> — {emoji} {p[1]} {role}\n"

    if not osnova and not rezerv:
        text += "В клубе пока нет игроков."
        
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"manage_club_{club_id}", style=ButtonStyle.DANGER)]])
    await safe_edit_text(callback.message, text, reply_markup=kb)

@dp.callback_query(F.data.startswith("club_search_players_"))
async def cb_club_search_players(callback: CallbackQuery, state: FSMContext):
    try: await callback.answer()
    except TelegramBadRequest: pass
    club_id = int(callback.data.split("_")[3])
    
    can_proceed, error_msg = await check_limit(callback.from_user.id, "club_search", daily_limit=2, cooldown_hours=2)
    if not can_proceed:
        try: await callback.answer(error_msg, show_alert=True)
        except TelegramBadRequest: pass
        return

    await state.update_data(active_club_id=club_id)
    await safe_edit_text(
        callback.message,
        "🔍 <b>Поиск игроков</b>\n\nШаг 1 из 2. Напишите, какие позиции вам нужны (например: Нападающий, Защитник):", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"manage_club_{club_id}", style=ButtonStyle.DANGER)]])
    )
    await state.set_state(Form.club_search_positions)

@dp.message(Form.club_search_positions, F.text)
async def process_club_search_pos(message: Message, state: FSMContext):
    await state.update_data(needed_pos=message.text)
    await message.answer("Шаг 2 из 2. Напишите ваши <b>требования</b> к игрокам (например: опыт от 100 часов, онлайн каждый день):", parse_mode="HTML")
    await state.set_state(Form.club_search_requirements)

@dp.message(Form.club_search_requirements, F.text)
async def process_club_search_reqs(message:
