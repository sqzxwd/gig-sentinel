"""Unit tests for Telegram bot components, keyboards, and sentinel poll cycle."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot

from src.bot import (
    build_filters_keyboard,
    build_main_menu_keyboard,
    build_order_action_keyboard,
    build_profile_keyboard,
    sentinel_poll_cycle,
)
from src.database import Database
from src.models import FreelanceOrder, FreelancerProfile
from src.parser import HabrFreelanceParser


def test_keyboards_structure():
    """Verify inline keyboards contain appropriate action buttons."""
    main_menu = build_main_menu_keyboard()
    assert len(main_menu.inline_keyboard) >= 2

    profile_kb = build_profile_keyboard(is_active=True)
    assert any("паузу" in btn.text for row in profile_kb.inline_keyboard for btn in row)

    filters_kb = build_filters_keyboard()
    assert any("Добавить" in btn.text for row in filters_kb.inline_keyboard for btn in row)

    order = FreelanceOrder(
        id="habr_123",
        title="Test Task",
        url="https://freelance.habr.com/tasks/123",
        description="Desc",
        published_at=datetime.now(UTC),
    )
    order_kb = build_order_action_keyboard(order)
    button_callbacks = [
        btn.callback_data for row in order_kb.inline_keyboard for btn in row if btn.callback_data
    ]
    assert "pitch:habr_123" in button_callbacks
    assert "dismiss:habr_123" in button_callbacks


@pytest.mark.asyncio
async def test_sentinel_poll_cycle_with_deduplication(tmp_path: Path):
    """Verify background poll cycle delivers matching orders and dedupes on next cycle."""
    db_file = tmp_path / "bot_test.db"
    async with Database(db_file) as db:
        # Create user with keyword 'python'
        user = FreelancerProfile(
            telegram_id=777,
            full_name="Bot Tester",
            is_active=True,
        )
        await db.upsert_user(user)
        await db.add_keyword(777, "python")

        # Mock Bot
        mock_bot = MagicMock(spec=Bot)
        mock_bot.send_message = AsyncMock()

        # Mock Orders
        order_match = FreelanceOrder(
            id="habr_order_1",
            title="Разработка скрипта на Python",
            url="https://freelance.habr.com/tasks/1",
            description="Парсер данных",
            published_at=datetime.now(UTC),
            tags=["Python"],
        )
        order_nomatch = FreelanceOrder(
            id="habr_order_2",
            title="Дизайн сайта Figma",
            url="https://freelance.habr.com/tasks/2",
            description="Отрисовка UI",
            published_at=datetime.now(UTC),
            tags=["UI/UX"],
        )

        mock_parser = MagicMock(spec=HabrFreelanceParser)
        mock_parser.fetch_orders = AsyncMock(return_value=[order_match, order_nomatch])

        # First polling cycle: should deliver 1 message
        dispatched_1 = await sentinel_poll_cycle(
            bot=mock_bot,
            db=db,
            parser=mock_parser,
        )
        assert dispatched_1 == 1
        assert mock_bot.send_message.call_count == 1

        # Check call arguments
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 777
        assert "Разработка скрипта на Python" in call_kwargs["text"]

        # Verify order was saved to cache
        cached = await db.get_order("habr_order_1")
        assert cached is not None
        assert cached.id == "habr_order_1"

        # Verify order was recorded in seen_orders
        assert await db.is_order_seen("habr_order_1", 777) is True

        # Second polling cycle with same orders: should deliver 0 new messages!
        mock_bot.send_message.reset_mock()
        dispatched_2 = await sentinel_poll_cycle(
            bot=mock_bot,
            db=db,
            parser=mock_parser,
        )
        assert dispatched_2 == 0
        assert mock_bot.send_message.call_count == 0
