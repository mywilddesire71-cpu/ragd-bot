import asyncio
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ==========================================
# 1. НАСТРОЙКА ЛОГИРОВАНИЯ
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# 2. НАСТРОЙКИ БОТА
# ==========================================
# Вписан ваш ID
ADMIN_IDS = [2046978907] 

# --- ИМИТАЦИЯ БАЗЫ ДАННЫХ ---
db_profiles = {} 
db_transfers = []

# ==========================================
# 3. СОСТОЯНИЯ И ВАЛИДАЦИЯ
# ==========================================
class TransferForm(StatesGroup):
    waiting_for_nickname = State()
    waiting_for_old_club = State()
    waiting_for_new_club = State()

class ProfileForm(StatesGroup):
    waiting_for_first_team = State()
    waiting_for_second_team = State()

def is_valid_text(text: str, min_len: int = 2, max_len: int = 30) -> bool:
    if not text:
        return False
    text = text.strip()
    return min_len <= len(text) <= max_len

# ==========================================
# 4. КЛАВИАТУРЫ
# ==========================================
def get_main_menu(user_id: int):
    buttons = [
        [InlineKeyboardButton(text="🔄 Переходы", style="primary", callback_data="menu_transfers")],
        [
            InlineKeyboardButton(text="🔍 Поиск трансферов", style="success", callback_data="search_transfers"),
            InlineKeyboardButton(text="👥 Поиск игроков", style="danger", callback_data="search_players")
        ],
        [InlineKeyboardButton(text="👤 Мой профиль", style="primary", callback_data="profile")]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="🛠 Админ-панель", style="danger", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_profile_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Изменить 1-ю основу", style="success", callback_data="edit_team1")],
        [InlineKeyboardButton(text="⚙️ Изменить 2-ю основу", style="danger", callback_data="edit_team2")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", style="primary", callback_data="back_to_menu")]
    ])

def get_cancel_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", style="danger", callback_data="back_to_menu")]
    ])

def get_admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", style="primary", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🧹 Очистить переходы", style="danger", callback_data="admin_clear")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", style="success", callback_data="back_to_menu")]
    ])

router = Router()

# ==========================================
# 5. ОБРАБОТЧИКИ (ХЭНДЛЕРЫ)
# ==========================================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    logger.info(f"Пользователь {message.from_user.id} (@{message.from_user.username}) запустил бота")
    await message.answer(
        "Привет! Это бот для поиска игроков и трансферов.\nВыбери действие:",
        reply_markup=get_main_menu(message.from_user.id)
    )

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu(callback.from_user.id))
    await callback.answer()

# --- ПЕРЕХОДЫ ---
@router.callback_query(F.data == "menu_transfers")
async def start_transfer(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TransferForm.waiting_for_nickname)
    await callback.message.edit_text(
        "Оформление перехода.\n\nШаг 1: Введите ваш **ник в Roblox** 👇\n(Только текст, от 2 до 20 символов)",
        reply_markup=get_cancel_menu()
    )
    await callback.answer()

@router.message(TransferForm.waiting_for_nickname)
async def transfer_nick(message: Message, state: FSMContext):
    if not message.text or not is_valid_text(message.text, 2, 20):
        await message.answer("❌ Ошибка! Пожалуйста, отправьте **текст** (ваш ник), длиной от 2 до 20 символов.")
        logger.warning(f"Пользователь {message.from_user.id} ввел неверный ник.")
        return 
    
    await state.update_data(nick=message.text.strip())
    await state.set_state(TransferForm.waiting_for_old_club)
    await message.answer(f"Ник сохранен: `{message.text}`\n\nШаг 2: Из какого **клуба вы уходите**?", reply_markup=get_cancel_menu())

@router.message(TransferForm.waiting_for_old_club)
async def transfer_old_club(message: Message, state: FSMContext):
    if not message.text or not is_valid_text(message.text, 2, 30):
        await message.answer("❌ Ошибка! Название клуба должно быть текстом от 2 до 30 символов.")
        return
        
    await state.update_data(old_club=message.text.strip())
    await state.set_state(TransferForm.waiting_for_new_club)
    await message.answer(f"Уходите из: `{message.text}`\n\nШаг 3: В какой **клуб вы переходите**?", reply_markup=get_cancel_menu())

@router.message(TransferForm.waiting_for_new_club)
async def transfer_new_club(message: Message, state: FSMContext):
    if not message.text or not is_valid_text(message.text, 2, 30):
        await message.answer("❌ Ошибка! Название клуба должно быть текстом от 2 до 30 символов.")
        return

    await state.update_data(new_club=message.text.strip())
    data = await state.get_data()
    
    transfer_data = {
        "user_id": message.from_user.id,
        "nick": data['nick'],
        "from_club": data['old_club'],
        "to_club": data['new_club']
    }
    db_transfers.append(transfer_data)
    logger.info(f"Создан переход: {transfer_data['nick']} из {transfer_data['from_club']} в {transfer_data['to_club']}")
    
    await message.answer(
        f"✅ **Заявка на переход создана!**\n\n"
        f"🎮 Ник: `{data['nick']}`\n"
        f"🏃 Из клуба: {data['old_club']}\n"
        f"🏁 В клуб: {data['new_club']}",
        reply_markup=get_main_menu(message.from_user.id)
    )
    await state.clear()

# --- ПОИСК ---
@router.callback_query(F.data == "search_transfers")
async def show_transfers(callback: CallbackQuery):
    if not db_transfers:
        await callback.message.edit_text("Пока нет активных заявок на переход.", reply_markup=get_main_menu(callback.from_user.id))
    else:
        text = "🔍 **Активные переходы:**\n\n"
        for t in db_transfers:
            text += f"👤 `{t['nick']}`: {t['from_club']} ➡️ {t['to_club']}\n"
        await callback.message.edit_text(text, reply_markup=get_main_menu(callback.from_user.id))
    await callback.answer()

@router.callback_query(F.data == "search_players")
async def show_players(callback: CallbackQuery):
    if not db_profiles:
        await callback.message.edit_text("В базе пока нет игроков с заполненным профилем.", reply_markup=get_main_menu(callback.from_user.id))
    else:
        text = "👥 **Игроки в базе:**\n\n"
        for uid, p in db_profiles.items():
            text += f"🎮 `{p.get('nick', 'Неизвестно')}`\n"
            text += f"🟢 1-я основа: {p.get('team1', 'Не выбрана')}\n"
            text += f"🔴 2-я основа: {p.get('team2', 'Не выбрана')}\n\n"
        await callback.message.edit_text(text, reply_markup=get_main_menu(callback.from_user.id))
    await callback.answer()

# --- ПРОФИЛЬ ---
@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in db_profiles:
        db_profiles[user_id] = {"nick": callback.from_user.first_name, "team1": "Не выбрана", "team2": "Не выбрана"}
        
    profile = db_profiles[user_id]
    text = (
        f"👤 **Твой профиль**\n\n"
        f"🎮 Ник в Telegram: `{profile['nick']}`\n"
        f"🟢 1-я основа: **{profile['team1']}**\n"
        f"🔴 2-я основа: **{profile['team2']}**\n\n"
        "Нажми на кнопку ниже, чтобы изменить клубы."
    )
    await callback.message.edit_text(text, reply_markup=get_profile_menu())
    await callback.answer()

@router.callback_query(F.data == "edit_team1")
async def start_edit_team1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.waiting_for_first_team)
    await callback.message.edit_text("Введите название клуба для **Первой основы**:", reply_markup=get_cancel_menu())
    await callback.answer()

@router.message(ProfileForm.waiting_for_first_team)
async def process_team1(message: Message, state: FSMContext):
    if not message.text or not is_valid_text(message.text, 2, 30):
        await message.answer("❌ Ошибка! Введите текст от 2 до 30 символов.")
        return
    db_profiles[message.from_user.id]["team1"] = message.text.strip()
    await state.clear()
    logger.info(f"Пользователь {message.from_user.id} изменил 1-ю основу на {message.text}")
    await message.answer(f"✅ Первая основа изменена на: **{message.text}**", reply_markup=get_profile_menu())

@router.callback_query(F.data == "edit_team2")
async def start_edit_team2(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ProfileForm.waiting_for_second_team)
    await callback.message.edit_text("Введите название клуба для **Второй основы**:", reply_markup=get_cancel_menu())
    await callback.answer()

@router.message(ProfileForm.waiting_for_second_team)
async def process_team2(message: Message, state: FSMContext):
    if not message.text or not is_valid_text(message.text, 2, 30):
        await message.answer("❌ Ошибка! Введите текст от 2 до 30 символов.")
        return
    db_profiles[message.from_user.id]["team2"] = message.text.strip()
    await state.clear()
    logger.info(f"Пользователь {message.from_user.id} изменил 2-ю основу на {message.text}")
    await message.answer(f"✅ Вторая основа изменена на: **{message.text}**", reply_markup=get_profile_menu())

# ==========================================
# 6. АДМИН-ПАНЕЛЬ
# ==========================================
@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ У вас нет доступа к этой панели.", show_alert=True)
        logger.warning(f"Пользователь {callback.from_user.id} пытался зайти в админку!")
        return
        
    await callback.message.edit_text("🛠 **Админ-панель**\nВыберите действие:", reply_markup=get_admin_menu())
    await callback.answer()

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    text = (
        f"📊 **Статистика:**\n\n"
        f"👥 Всего пользователей в базе: {len(db_profiles)}\n"
        f"🔄 Активных переходов: {len(db_transfers)}"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_menu())
    await callback.answer()

@router.callback_query(F.data == "admin_clear")
async def admin_clear(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    global db_transfers
    db_transfers.clear()
    logger.info(f"Админ {callback.from_user.id} очистил базу переходов.")
    await callback.message.edit_text("✅ База переходов успешно очищена.", reply_markup=get_admin_menu())
    await callback.answer()

# ==========================================
# 7. ЗАПУСК
# ==========================================
async def main():
    # Вставлен ваш токен (ОБЯЗАТЕЛЬНО СМЕНИТЕ ЕГО В BOTFATHER!)
    bot = Bot(token="8846789160:AAFkbP2SUZz0R5NiTdusKgEThHHNPjZqf_Q")
    dp = Dispatcher()
    dp.include_router(router)
    logger.info("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
