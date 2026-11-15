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
ADMIN_IDS = [2046978907] 

# --- ИМИТАЦИЯ БАЗЫ ДАННЫХ (в памяти) ---
db_profiles = {} 
db_transfers = []
db_clubs = ["Red Dragons", "Blue Wolves", "FC Lightning", "Night Owls", "Golden Eagles"]

# ==========================================
# 3. СОСТОЯНИЯ (FSM)
# ==========================================
class TransferForm(StatesGroup):
    waiting_for_nicks = State()
    waiting_for_club = State()

class AdForm(StatesGroup):
    waiting_for_text = State()
    waiting_for_link = State()

# ==========================================
# 4. КЛАВИАТУРЫ
# ==========================================
def get_main_menu(user_id: int):
    buttons = [
        [
            InlineKeyboardButton(text="🔍 Поиск клуба", style="primary", callback_data="search_club"),
            InlineKeyboardButton(text="🔄 Переход в клуб", style="success", callback_data="transfer_menu")
        ],
        [
            InlineKeyboardButton(text="👤 Профиль", style="primary", callback_data="profile"),
            InlineKeyboardButton(text="🏆 Карьера", style="success", callback_data="career")
        ],
        [
            InlineKeyboardButton(text="🤝 Поиск товы", style="primary", callback_data="search_teammates"),
            InlineKeyboardButton(text="👥 Поиск игроков", style="success", callback_data="search_players")
        ],
        [
            InlineKeyboardButton(text="📢 Реклама", style="danger", callback_data="ad_menu"),
            InlineKeyboardButton(text="🛡 Поддержка", style="primary", callback_data="support")
        ],
        [
            InlineKeyboardButton(text="ℹ️ Информация", style="primary", callback_data="info")
        ]
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="🛠 Админ-панель", style="danger", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в меню", style="danger", callback_data="back_to_menu")]
    ])

def get_profile_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Сменить 1-ю основу", style="success", callback_data="edit_team1")],
        [InlineKeyboardButton(text="⚙️ Сменить 2-ю основу", style="success", callback_data="edit_team2")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", style="danger", callback_data="back_to_menu")]
    ])

def get_cancel_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", style="danger", callback_data="back_to_menu")]
    ])

router = Router()

# ==========================================
# 5. ОБРАБОТЧИКИ КНОПОК ГЛАВНОГО МЕНЮ
# ==========================================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    logger.info(f"Пользователь {message.from_user.id} запустил бота")
    await message.answer(
        "👋 **Добро пожаловать в бот!**\nВыберите нужный раздел на клавиатуре ниже:",
        reply_markup=get_main_menu(message.from_user.id),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=get_main_menu(callback.from_user.id))
    await callback.answer()

# --- 1. ПОИСК КЛУБА ---
@router.callback_query(F.data == "search_club")
async def search_club(callback: CallbackQuery):
    text = "🔍 **Доступные клубы:**\n\n"
    for i, club in enumerate(db_clubs, 1):
        text += f"{i}. 🛡 {club}\n"
    text += "\n*Чтобы вступить в клуб, используйте кнопку 'Переход в клуб'.*"
    await callback.message.edit_text(text, reply_markup=get_back_menu(), parse_mode="Markdown")
    await callback.answer()

# --- 2. ПЕРЕХОД В КЛУБ (FSM) ---
@router.callback_query(F.data == "transfer_menu")
async def transfer_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TransferForm.waiting_for_nicks)
    await callback.message.edit_text(
        "🔄 **Оформление перехода**\n\n"
        "Шаг 1: Напишите ники игроков, которые переходят (через запятую или пробел):",
        reply_markup=get_cancel_menu(), parse_mode="Markdown"
    )
    await callback.answer()

@router.message(TransferForm.waiting_for_nicks)
async def process_nicks(message: Message, state: FSMContext):
    if not message.text or len(message.text.strip()) < 2:
        await message.answer("❌ Ошибка! Введите текст (ники игроков).")
        return
    await state.update_data(nicks=message.text.strip())
    await state.set_state(TransferForm.waiting_for_club)
    await message.answer("✅ Ники сохранены.\n\nШаг 2: В какой **клуб** они переходят?", reply_markup=get_cancel_menu(), parse_mode="Markdown")

@router.message(TransferForm.waiting_for_club)
async def process_transfer_club(message: Message, state: FSMContext):
    if not message.text or len(message.text.strip()) < 2:
        await message.answer("❌ Ошибка! Введите название клуба текстом.")
        return
    data = await state.get_data()
    nicks = data['nicks']
    club = message.text.strip()
    
    db_transfers.append({"user_id": message.from_user.id, "nicks": nicks, "club": club})
    logger.info(f"Новый переход: {nicks} в {club}")
    
    await message.answer(
        f"✅ **Заявка на переход создана!**\n\n"
        f"🎮 Игроки: `{nicks}`\n"
        f"🏁 Переходят в клуб: **{club}**",
        reply_markup=get_main_menu(message.from_user.id), parse_mode="Markdown"
    )
    await state.clear()

# --- 3. ПРОФИЛЬ ---
@router.callback_query(F.data == "profile")
async def profile_menu(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in db_profiles:
        db_profiles[uid] = {"nick": callback.from_user.first_name, "status": "Свободный агент", "team1": "Нет", "team2": "Нет"}
    
    p = db_profiles[uid]
    text = (
        f"👤 **Ваш профиль**\n\n"
        f"🎮 Ник: `{p['nick']}`\n"
        f"📊 Статус карьеры: **{p['status']}**\n\n"
        f"🟢 1-я основа: **{p['team1']}**\n"
        f"🔴 2-я основа: **{p['team2']}**\n\n"
        f"*Вы можете изменить свои клубы (основы) ниже:*"
    )
    await callback.message.edit_text(text, reply_markup=get_profile_menu(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "edit_team1")
async def edit_team1(callback: CallbackQuery, state: FSMContext):
    await state.update_data(edit_team="team1")
    await callback.message.edit_text("Введите название клуба для **1-й основы**:", reply_markup=get_cancel_menu(), parse_mode="Markdown")
    await state.set_state(TransferForm.waiting_for_club) # Используем то же состояние, но с флагом
    await callback.answer()

# --- 4. КАРЬЕРА ---
@router.callback_query(F.data == "career")
async def career_menu(callback: CallbackQuery):
    text = (
        "🏆 **Ваша карьера**\n\n"
        "📈 Матчи: **15**\n"
        "⚽ Голы: **7**\n"
        "🅰️ Передачи: **4**\n"
        "🟨 Желтые карточки: **1**\n\n"
        "📋 *История переходов:*\n"
        "➖ Red Dragons ➡️ Blue Wolves (15.10.2026)"
    )
    await callback.message.edit_text(text, reply_markup=get_back_menu(), parse_mode="Markdown")
    await callback.answer()

# --- 5. ПОИСК ТОВЫ ---
@router.callback_query(F.data == "search_teammates")
async def search_teammates(callback: CallbackQuery):
    text = (
        "🤝 **Поиск товарищей (тов)**\n\n"
        "Игроки, которые ищут напарников прямо сейчас:\n\n"
        "👤 @Ivan: Ищу тову для 2х2, 1-я основа Blue Wolves\n"
        "👤 @Max: Нужен сокомандник в Night Owls\n\n"
        "*Чтобы подать заявку, напишите в поддержку.*"
    )
    await callback.message.edit_text(text, reply_markup=get_back_menu(), parse_mode="Markdown")
    await callback.answer()

# --- 6. ПОИСК ИГРОКОВ ---
@router.callback_query(F.data == "search_players")
async def search_players(callback: CallbackQuery):
    if not db_profiles:
        await callback.message.edit_text("👥 База игроков пока пуста. Заполните профиль!", reply_markup=get_back_menu())
    else:
        text = "👥 **Список игроков:**\n\n"
        for uid, p in db_profiles.items():
            text += f"🎮 `{p['nick']}` | 1-я основа: {p['team1']}\n"
        await callback.message.edit_text(text, reply_markup=get_back_menu(), parse_mode="Markdown")
    await callback.answer()

# --- 7. РЕКЛАМА (FSM) ---
@router.callback_query(F.data == "ad_menu")
async def ad_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdForm.waiting_for_text)
    await callback.message.edit_text(
        "📢 **Раздел Рекламы**\n\n"
        "Шаг 1: Напишите текст вашего рекламного объявления:",
        reply_markup=get_cancel_menu(), parse_mode="Markdown"
    )
    await callback.answer()

@router.message(AdForm.waiting_for_text)
async def process_ad_text(message: Message, state: FSMContext):
    if not message.text: return
    await state.update_data(ad_text=message.text)
    await state.set_state(AdForm.waiting_for_link)
    await message.answer("✅ Текст сохранен.\n\nШаг 2: Отправьте **ссылку** (URL) для вашей рекламы:", reply_markup=get_cancel_menu(), parse_mode="Markdown")

@router.message(AdForm.waiting_for_link)
async def process_ad_link(message: Message, state: FSMContext):
    if not message.text: return
    data = await state.get_data()
    logger.info(f"Реклама от {message.from_user.id}: {data['ad_text']} | {message.text}")
    await message.answer("✅ **Ваша реклама отправлена на модерацию администратору!**", reply_markup=get_main_menu(message.from_user.id))
    await state.clear()

# --- 8. ПОДДЕРЖКА ---
@router.callback_query(F.data == "support")
async def support_menu(callback: CallbackQuery):
    text = (
        "🛡 **Техническая поддержка**\n\n"
        "Если у вас возникли проблемы или вопросы:\n"
        "1. Напишите нашему менеджеру: @admin_username\n"
        "2. Или отправьте тикет в бот: /ticket\n\n"
        "⏳ *Среднее время ответа: 15 минут.*"
    )
    await callback.message.edit_text(text, reply_markup=get_back_menu(), parse_mode="Markdown")
    await callback.answer()

# --- 9. ИНФОРМАЦИЯ ---
@router.callback_query(F.data == "info")
async def info_menu(callback: CallbackQuery):
    text = (
        "ℹ️ **Информация о боте**\n\n"
        "Данный бот предназначен для управления футбольными клубами в Roblox.\n"
        "📅 Версия бота: 2.0\n"
        "👨‍💻 Разработчик: @developer_username\n"
        "📋 Пользовательское соглашение: /terms\n\n"
        "*Соблюдайте правила и играйте честно!*"
    )
    await callback.message.edit_text(text, reply_markup=get_back_menu(), parse_mode="Markdown")
    await callback.answer()

# ==========================================
# 6. ОБРАБОТКА ВВОДА ДЛЯ ОСНОВ (ПРОДОЛЖЕНИЕ)
# ==========================================
# (Этот хэндлер ловит ввод текста, когда мы меняем основу)
@router.message(TransferForm.waiting_for_club)
async def save_team_base(message: Message, state: FSMContext):
    # Проверяем, не находимся ли мы в процессе перехода
    current_state = await state.get_state()
    if current_state == TransferForm.waiting_for_club.state:
        # Если мы меняем основу через профиль
        data = await state.get_data()
        if 'edit_team' in data:
            team_type = data['edit_team']
            if message.from_user.id not in db_profiles:
                db_profiles[message.from_user.id] = {"nick": message.from_user.first_name, "status": "Свободный агент", "team1": "Нет", "team2": "Нет"}
            db_profiles[message.from_user.id][team_type] = message.text.strip()
            await state.clear()
            await message.answer(f"✅ Успешно изменено!", reply_markup=get_profile_menu())
            return

# ==========================================
# 7. АДМИН-ПАНЕЛЬ
# ==========================================
@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    text = f"🛠 **Админ-панель**\n\nПереходов в базе: {len(db_transfers)}\nПользователей: {len(db_profiles)}"
    await callback.message.edit_text(text, reply_markup=get_back_menu(), parse_mode="Markdown")
    await callback.answer()

# ==========================================
# 8. ЗАПУСК
# ==========================================
async def main():
    # ⚠️ СМЕНИТЕ ТОКЕН В BOTFATHER! ⚠️
    bot = Bot(token="8846789160:AAFkbP2SUZz0R5NiTdusKgEThHHNPjZqf_Q")
    dp = Dispatcher()
    dp.include_router(router)
    logger.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
