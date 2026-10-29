"""Telegram bot implementation for Gig Sentinel using aiogram 3."""

import asyncio
import logging
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.ai_pitcher import AIPitcher
from src.config import Settings
from src.config import settings as default_settings
from src.database import Database
from src.models import FreelanceOrder, FreelancerProfile
from src.parser import HabrFreelanceParser, matches_keywords

logger = logging.getLogger(__name__)

router = Router(name="gig_sentinel_router")


# -----------------------------------------------------------------------------
# FSM STATES FOR INTERACTIVE PROFILE & FILTER UPDATES
# -----------------------------------------------------------------------------


class ProfileEditStates(StatesGroup):
    waiting_for_specialization = State()
    waiting_for_skills = State()
    waiting_for_experience = State()
    waiting_for_portfolio = State()
    waiting_for_rate = State()


class FilterStates(StatesGroup):
    waiting_for_keyword = State()


# -----------------------------------------------------------------------------
# KEYBOARDS BUILDERS
# -----------------------------------------------------------------------------


def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main navigation keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Мой профиль", callback_data="menu:profile"),
                InlineKeyboardButton(text="🔍 Мои фильтры", callback_data="menu:filters"),
            ],
            [
                InlineKeyboardButton(
                    text="⚡️ Статус мониторинга", callback_data="menu:toggle_status"
                ),
                InlineKeyboardButton(text="ℹ️ О сервисе", callback_data="menu:help"),
            ],
        ]
    )


def build_order_action_keyboard(order: FreelanceOrder) -> InlineKeyboardMarkup:
    """Action buttons shown under every matched freelance order."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✍️ Сгенерировать отклик (AI)",
                    callback_data=f"pitch:{order.id}",
                ),
            ],
            [
                InlineKeyboardButton(text="🔗 Открыть на Хабре", url=order.url),
                InlineKeyboardButton(text="❌ Скрыть", callback_data=f"dismiss:{order.id}"),
            ],
        ]
    )


def build_profile_keyboard(is_active: bool) -> InlineKeyboardMarkup:
    """Profile management buttons."""
    status_text = "⏸ Поставить на паузу" if is_active else "▶️ Включить мониторинг"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Изменить специализацию", callback_data="prof:spec"),
                InlineKeyboardButton(text="🛠 Изменить навыки", callback_data="prof:skills"),
            ],
            [
                InlineKeyboardButton(text="⏳ Изменить опыт", callback_data="prof:exp"),
                InlineKeyboardButton(text="🌐 Портфолио", callback_data="prof:port"),
            ],
            [
                InlineKeyboardButton(text=status_text, callback_data="menu:toggle_status"),
                InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu:main"),
            ],
        ]
    )


def build_filters_keyboard() -> InlineKeyboardMarkup:
    """Filters & keyword management buttons."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Добавить фильтр", callback_data="filter:add"),
                InlineKeyboardButton(text="🗑 Очистить все", callback_data="filter:clear"),
            ],
            [
                InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu:main"),
            ],
        ]
    )


# -----------------------------------------------------------------------------
# HANDLERS: /start, /profile, /filter, /help
# -----------------------------------------------------------------------------


@router.message(CommandStart())
async def handle_start(message: Message, db: Database) -> None:
    """Handle /start command. Registers user if new and renders welcome dashboard."""
    if not message.from_user:
        return

    user_id = message.from_user.id
    existing_user = await db.get_user(user_id)

    if not existing_user:
        new_profile = FreelancerProfile(
            telegram_id=user_id,
            username=message.from_user.username,
            full_name=message.from_user.full_name or "Фрилансер",
            specialization="Python Backend & AI Developer",
            skills=["Python", "FastAPI", "Telegram Bot", "PostgreSQL", "AI"],
            experience_years=3,
        )
        await db.upsert_user(new_profile)
        # Add starter default keywords
        await db.add_keyword(user_id, "python")
        await db.add_keyword(user_id, "бот")
        await db.add_keyword(user_id, "ai")

    welcome_text = (
        f"👋 <b>Добро пожаловать в Gig Sentinel, {escape(message.from_user.first_name)}!</b>\n\n"
        "🛡 <b>Gig Sentinel</b> — коммерческий радар и AI-ассистент для фрилансеров:\n"
        "• <b>Мгновенный мониторинг ленты Хабр Фриланс:</b> сбор новых заказов в реальном времени.\n"
        "• <b>Умная дедупликация:</b> вы никогда не получите один и тот же заказ дважды.\n"
        "• <b>Фильтрация:</b> отслеживание заказов строго по вашим ключевым и стоп-словам.\n"
        "• <b>AI Pitch Generator:</b> генерация персонализированных коммерческих откликов в 1 клик.\n\n"
        "Используйте кнопки меню ниже или команды:\n"
        "• <code>/profile</code> — настроить ваш опыт и навыки\n"
        "• <code>/filter</code> — управление ключевыми словами\n"
        "• <code>/help</code> — документация по работе с ботом"
    )

    await message.answer(
        welcome_text,
        reply_markup=build_main_menu_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("profile"))
async def handle_profile_command(message: Message, db: Database) -> None:
    """Handle /profile command."""
    if not message.from_user:
        return

    profile = await db.get_user(message.from_user.id)
    if not profile:
        profile = FreelancerProfile(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        await db.upsert_user(profile)

    positives, _ = await db.get_user_keywords(message.from_user.id)
    card_text = profile.to_telegram_card(keywords_count=len(positives))

    await message.answer(
        card_text,
        reply_markup=build_profile_keyboard(profile.is_active),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("filter"))
async def handle_filter_command(message: Message, db: Database) -> None:
    """Handle /filter command with viewing and adding quick keywords."""
    if not message.from_user:
        return

    # Check for direct arguments, e.g. /filter add python or /filter del bot
    args = message.text.split()[1:] if message.text else []
    if len(args) >= 2:
        action = args[0].lower()
        keyword = " ".join(args[1:]).strip()

        if action in ("add", "+"):
            is_neg = keyword.startswith("!") or keyword.startswith("-")
            clean_word = keyword.lstrip("!- ").strip()
            if clean_word:
                await db.add_keyword(message.from_user.id, clean_word, is_negative=is_neg)
                kw_type = "Стоп-слово (минус-фильтр)" if is_neg else "Ключевое слово"
                await message.answer(
                    f"✅ {kw_type} <b>{escape(clean_word)}</b> добавлено!",
                    parse_mode=ParseMode.HTML,
                )
        elif action in ("del", "remove", "-"):
            clean_word = keyword.lstrip("!- ").strip()
            deleted = await db.remove_keyword(message.from_user.id, clean_word)
            if deleted:
                await message.answer(
                    f"🗑 Фильтр <b>{escape(clean_word)}</b> удален.", parse_mode=ParseMode.HTML
                )
            else:
                await message.answer(
                    f"⚠️ Фильтр <b>{escape(clean_word)}</b> не найден.", parse_mode=ParseMode.HTML
                )

    positives, negatives = await db.get_user_keywords(message.from_user.id)
    pos_str = (
        ", ".join(f"<code>{p}</code>" for p in positives)
        if positives
        else "<i>все заказы (нет ограничений)</i>"
    )
    neg_str = (
        ", ".join(f"<code>{n}</code>" for n in negatives) if negatives else "<i>нет стоп-слов</i>"
    )

    filter_text = (
        "🔍 <b>Ваши настройки фильтрации заказов:</b>\n\n"
        f"🟢 <b>Ключевые слова (поиск):</b>\n{pos_str}\n\n"
        f"🔴 <b>Стоп-слова (исключение):</b>\n{neg_str}\n\n"
        "💡 <i>Совет: Для быстрого добавления отправьте команду:</i>\n"
        "• <code>/filter add python</code> — добавить ключевое слово\n"
        "• <code>/filter add !wordpress</code> — добавить стоп-слово\n"
        "• <code>/filter del python</code> — удалить фильтр"
    )

    await message.answer(
        filter_text,
        reply_markup=build_filters_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("help"))
async def handle_help_command(message: Message) -> None:
    """Handle /help command."""
    help_text = (
        "📖 <b>Справка по использованию Gig Sentinel:</b>\n\n"
        "1. <b>Как работает мониторинг?</b>\n"
        "Бот каждые несколько минут опрашивает RSS-ленту заказов Хабр Фриланс. "
        "Каждый новый заказ проверяется по вашему списку ключевых слов и стоп-слов. "
        "Благодаря таблице <code>seen_orders</code> заказы отправляются строго 1 раз.\n\n"
        "2. <b>Генерация коммерческого отклика (AI Pitch):</b>\n"
        "Под каждым заказом есть кнопка «✍️ Сгенерировать отклик». Бот совмещает данные ТЗ заказа "
        "и ваш профиль (навыки, специализацию, опыт, ставку) и формирует структурированный отклик "
        "с коммерческим хуком, планом решения и призывом к действию (CTA).\n\n"
        "3. <b>Команды бота:</b>\n"
        "• <code>/start</code> — Панель управления и статус\n"
        "• <code>/profile</code> — Профиль специалиста\n"
        "• <code>/filter</code> — Управление фильтрами\n"
        "• <code>/help</code> — Это справочное сообщение"
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML)


# -----------------------------------------------------------------------------
# CALLBACK QUERY HANDLERS
# -----------------------------------------------------------------------------


@router.callback_query(F.data == "menu:main")
async def callback_menu_main(callback: CallbackQuery) -> None:
    """Return to main menu."""
    await callback.answer()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            "🛡 <b>Главное меню Gig Sentinel</b>\nВыберите действие ниже:",
            reply_markup=build_main_menu_keyboard(),
            parse_mode=ParseMode.HTML,
        )


@router.callback_query(F.data == "menu:profile")
async def callback_menu_profile(callback: CallbackQuery, db: Database) -> None:
    """Show profile card from callback."""
    await callback.answer()
    profile = await db.get_user(callback.from_user.id)
    if not profile:
        profile = FreelancerProfile(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        await db.upsert_user(profile)

    positives, _ = await db.get_user_keywords(callback.from_user.id)
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            profile.to_telegram_card(keywords_count=len(positives)),
            reply_markup=build_profile_keyboard(profile.is_active),
            parse_mode=ParseMode.HTML,
        )


@router.callback_query(F.data == "menu:filters")
async def callback_menu_filters(callback: CallbackQuery, db: Database) -> None:
    """Show filters from callback."""
    await callback.answer()
    positives, negatives = await db.get_user_keywords(callback.from_user.id)
    pos_str = (
        ", ".join(f"<code>{p}</code>" for p in positives)
        if positives
        else "<i>все заказы (нет ограничений)</i>"
    )
    neg_str = (
        ", ".join(f"<code>{n}</code>" for n in negatives) if negatives else "<i>нет стоп-слов</i>"
    )

    filter_text = (
        "🔍 <b>Настройки фильтрации заказов:</b>\n\n"
        f"🟢 <b>Ключевые слова:</b>\n{pos_str}\n\n"
        f"🔴 <b>Стоп-слова:</b>\n{neg_str}\n\n"
        "Нажмите «Добавить фильтр» или используйте команду <code>/filter add &lt;слово&gt;</code>."
    )

    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            filter_text,
            reply_markup=build_filters_keyboard(),
            parse_mode=ParseMode.HTML,
        )


@router.callback_query(F.data == "menu:toggle_status")
async def callback_toggle_status(callback: CallbackQuery, db: Database) -> None:
    """Toggle user active alerts status."""
    profile = await db.get_user(callback.from_user.id)
    if not profile:
        await callback.answer("Профиль не найден", show_alert=True)
        return

    new_status = not profile.is_active
    await db.set_user_active(profile.telegram_id, new_status)
    status_label = "включен 🟢" if new_status else "выключен 🔴"
    await callback.answer(f"Мониторинг заказов {status_label}!", show_alert=True)

    positives, _ = await db.get_user_keywords(callback.from_user.id)
    updated_profile = await db.get_user(callback.from_user.id)
    if updated_profile and callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            updated_profile.to_telegram_card(keywords_count=len(positives)),
            reply_markup=build_profile_keyboard(updated_profile.is_active),
            parse_mode=ParseMode.HTML,
        )


@router.callback_query(F.data == "filter:clear")
async def callback_clear_filters(callback: CallbackQuery, db: Database) -> None:
    """Clear all keywords for user."""
    cleared = await db.clear_keywords(callback.from_user.id)
    await callback.answer(f"Удалено фильтров: {cleared}", show_alert=True)
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            "🗑 <b>Все фильтры очищены.</b> Теперь вам будут приходить все заказы подряд.",
            reply_markup=build_filters_keyboard(),
            parse_mode=ParseMode.HTML,
        )


@router.callback_query(F.data == "filter:add")
async def callback_add_filter_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt user to type a new keyword."""
    await callback.answer()
    await state.set_state(FilterStates.waiting_for_keyword)
    if callback.message and isinstance(callback.message, Message):
        await callback.message.answer(
            "✏️ <b>Отправьте ключевое слово</b> для фильтрации (например: <code>fastapi</code>).\n\n"
            "💡 Чтобы добавить <b>стоп-слово</b> (исключение), начните его со знака <code>!</code> "
            "(например: <code>!wordpress</code> или <code>!битрикс</code>).",
            parse_mode=ParseMode.HTML,
        )


@router.message(FilterStates.waiting_for_keyword)
async def process_filter_keyword_input(message: Message, state: FSMContext, db: Database) -> None:
    """Process incoming keyword from user text input."""
    raw_text = (message.text or "").strip()
    await state.clear()

    if not raw_text:
        await message.answer("⚠️ Пустое ключевое слово пропущено.")
        return

    is_neg = raw_text.startswith("!") or raw_text.startswith("-")
    clean_word = raw_text.lstrip("!- ").strip()

    if clean_word:
        await db.add_keyword(message.from_user.id, clean_word, is_negative=is_neg)
        kw_type = "Стоп-слово 🔴" if is_neg else "Ключевое слово 🟢"
        await message.answer(
            f"✅ {kw_type} <b>{escape(clean_word)}</b> успешно сохранено!",
            reply_markup=build_main_menu_keyboard(),
            parse_mode=ParseMode.HTML,
        )


# -----------------------------------------------------------------------------
# ORDER ACTIONS: AI PITCH GENERATION & DISMISS
# -----------------------------------------------------------------------------


@router.callback_query(F.data.startswith("pitch:"))
async def callback_generate_pitch(
    callback: CallbackQuery,
    db: Database,
    pitcher: AIPitcher,
) -> None:
    """Generate commercial proposal for order via AI Pitcher."""
    order_id = callback.data.split("pitch:", 1)[1] if callback.data else ""
    await callback.answer("⏳ Анализирую ТЗ и генерирую коммерческий отклик...")

    order = await db.get_order(order_id)
    if not order:
        await callback.message.answer("⚠️ Информация о данном заказе устарела или не найдена.")
        return

    profile = await db.get_user(callback.from_user.id)
    if not profile:
        profile = FreelancerProfile(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        await db.upsert_user(profile)

    pitch = await pitcher.generate_pitch(order=order, profile=profile)
    pitch_message = pitch.to_telegram_message(order_title=order.title)

    await callback.message.answer(
        pitch_message,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("dismiss:"))
async def callback_dismiss_order(callback: CallbackQuery) -> None:
    """Hide/dismiss order message."""
    await callback.answer("Заказ скрыт.")
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            "<i>Заказ скрыт из вашей ленты.</i>",
            parse_mode=ParseMode.HTML,
        )


# -----------------------------------------------------------------------------
# SENTINEL BACKGROUND WORKER (RSS POLLING & DEDUPLICATED DISPATCH)
# -----------------------------------------------------------------------------


async def sentinel_poll_cycle(
    bot: Bot,
    db: Database,
    parser: HabrFreelanceParser,
) -> int:
    """
    Execute one complete cycle of fetching, caching, and deduplicated distribution.

    Returns the count of newly dispatched notifications.
    """
    orders = await parser.fetch_orders()
    if not orders:
        logger.debug("No orders returned from RSS in this cycle.")
        return 0

    dispatched_count = 0

    # 1. Cache all fetched orders
    for order in orders:
        await db.save_order(order)

    # 2. Retrieve active subscribers and their keywords
    subscribers = await db.get_active_subscribers()
    if not subscribers:
        logger.debug("No active subscribers configured.")
        return 0

    # 3. Match and dispatch with strict deduplication
    for order in orders:
        for profile, positives, negatives in subscribers:
            user_id = profile.telegram_id

            # Check if user already saw this order
            if await db.is_order_seen(order.id, user_id):
                continue

            # Check keyword match
            if not matches_keywords(order, positives, negatives):
                continue

            # Deliver to Telegram
            try:
                text = order.to_telegram_html()
                keyboard = build_order_action_keyboard(order)
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                # Mark as seen immediately to prevent duplicate deliveries
                await db.mark_order_seen(order.id, user_id, is_notified=True)
                dispatched_count += 1
                logger.info("Dispatched order %s to user %s", order.id, user_id)
            except Exception as exc:
                logger.error("Failed to deliver order %s to user %s: %s", order.id, user_id, exc)

    return dispatched_count


async def run_sentinel_worker(
    bot: Bot,
    db: Database,
    parser: HabrFreelanceParser,
    poll_interval: int = 120,
) -> None:
    """Long-running background task that polls RSS feed periodically."""
    logger.info("Starting Gig Sentinel background worker (interval: %ds)...", poll_interval)
    while True:
        try:
            dispatched = await sentinel_poll_cycle(bot, db, parser)
            if dispatched > 0:
                logger.info("Sentinel cycle delivered %d new notifications.", dispatched)
        except asyncio.CancelledError:
            logger.info("Sentinel background worker received cancellation signal.")
            break
        except Exception as exc:
            logger.exception("Error during sentinel polling cycle: %s", exc)

        await asyncio.sleep(poll_interval)


# -----------------------------------------------------------------------------
# APPLICATION ENTRYPOINT & INITIALIZATION
# -----------------------------------------------------------------------------


def create_bot(config: Settings = default_settings) -> Bot:
    """Instantiate Aiogram Bot instance."""
    return Bot(
        token=config.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(db: Database, pitcher: AIPitcher) -> Dispatcher:
    """Instantiate and configure Aiogram Dispatcher with dependencies."""
    dp = Dispatcher()
    dp["db"] = db
    dp["pitcher"] = pitcher
    dp.include_router(router)
    return dp


async def main() -> None:
    """Main application runner."""
    config = default_settings
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    db = Database(config.get_db_path())
    await db.init_db()

    bot = create_bot(config)
    pitcher = AIPitcher(config)
    parser = HabrFreelanceParser(rss_url=config.habr_rss_url, timeout=config.request_timeout)
    dp = create_dispatcher(db=db, pitcher=pitcher)

    # Launch background sentinel worker
    worker_task = asyncio.create_task(
        run_sentinel_worker(
            bot=bot,
            db=db,
            parser=parser,
            poll_interval=config.poll_interval_seconds,
        )
    )

    try:
        logger.info("Gig Sentinel bot is online and polling Telegram updates...")
        await dp.start_polling(bot)
    finally:
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        await db.close()
        await bot.session.close()
        logger.info("Gig Sentinel shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
