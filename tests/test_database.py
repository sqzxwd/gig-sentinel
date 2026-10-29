"""Unit tests for asynchronous database operations and deduplication logic."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.database import Database
from src.models import FreelanceOrder, FreelancerProfile


@pytest.fixture
async def temp_db(tmp_path: Path):
    """Provide an isolated SQLite database instance for testing."""
    db_file = tmp_path / "test_gig_sentinel.db"
    async with Database(db_file) as db:
        yield db


@pytest.mark.asyncio
async def test_user_upsert_and_retrieval(temp_db: Database):
    """Verify creating and fetching freelancer profile."""
    profile = FreelancerProfile(
        telegram_id=12345678,
        username="dev_pro",
        full_name="Иван Иванов",
        specialization="Senior Python Engineer",
        skills=["Python", "FastAPI", "Docker", "aiogram"],
        experience_years=5,
        portfolio_url="https://github.com/devpro",
        hourly_rate=2500,
        is_active=True,
    )

    await temp_db.upsert_user(profile)
    retrieved = await temp_db.get_user(12345678)

    assert retrieved is not None
    assert retrieved.telegram_id == 12345678
    assert retrieved.username == "dev_pro"
    assert retrieved.full_name == "Иван Иванов"
    assert retrieved.specialization == "Senior Python Engineer"
    assert "FastAPI" in retrieved.skills
    assert retrieved.experience_years == 5
    assert retrieved.hourly_rate == 2500
    assert retrieved.is_active is True


@pytest.mark.asyncio
async def test_user_toggle_active_status(temp_db: Database):
    """Verify toggling active notifications status."""
    profile = FreelancerProfile(telegram_id=999, full_name="User")
    await temp_db.upsert_user(profile)

    assert (await temp_db.get_user(999)).is_active is True

    await temp_db.set_user_active(999, is_active=False)
    assert (await temp_db.get_user(999)).is_active is False

    await temp_db.set_user_active(999, is_active=True)
    assert (await temp_db.get_user(999)).is_active is True


@pytest.mark.asyncio
async def test_keywords_management(temp_db: Database):
    """Verify adding, retrieving, and removing positive and negative keywords."""
    profile = FreelancerProfile(telegram_id=1001, full_name="Filter Tester")
    await temp_db.upsert_user(profile)

    # Add positive keywords
    assert await temp_db.add_keyword(1001, "python") is True
    assert await temp_db.add_keyword(1001, "fastapi") is True

    # Duplicate should not re-insert
    assert await temp_db.add_keyword(1001, "python") is False

    # Add negative keyword (stop-word)
    assert await temp_db.add_keyword(1001, "wordpress", is_negative=True) is True

    positives, negatives = await temp_db.get_user_keywords(1001)
    assert sorted(positives) == ["fastapi", "python"]
    assert negatives == ["wordpress"]

    # Remove keyword
    assert await temp_db.remove_keyword(1001, "fastapi") is True
    positives, _ = await temp_db.get_user_keywords(1001)
    assert positives == ["python"]

    # Clear all keywords
    cleared = await temp_db.clear_keywords(1001)
    assert cleared == 2
    pos, neg = await temp_db.get_user_keywords(1001)
    assert len(pos) == 0
    assert len(neg) == 0


@pytest.mark.asyncio
async def test_strict_deduplication(temp_db: Database):
    """Verify seen_orders prevents duplicate deliveries of the same order."""
    profile = FreelancerProfile(telegram_id=2001, full_name="Dedup User")
    await temp_db.upsert_user(profile)

    order_id = "habr_777888"

    # Initially unseen
    assert await temp_db.is_order_seen(order_id, 2001) is False

    # Mark as seen
    marked = await temp_db.mark_order_seen(order_id, 2001, is_notified=True)
    assert marked is True

    # Now is seen
    assert await temp_db.is_order_seen(order_id, 2001) is True

    # Duplicate insertion returns False (ignored/already present)
    assert await temp_db.mark_order_seen(order_id, 2001) is False

    # Another user hasn't seen it yet
    assert await temp_db.is_order_seen(order_id, 3001) is False


@pytest.mark.asyncio
async def test_order_caching(temp_db: Database):
    """Verify caching and retrieving freelance orders."""
    order = FreelanceOrder(
        id="habr_12345",
        title="Скрипт парсинга на Python",
        url="https://freelance.habr.com/tasks/12345",
        description="Нужно написать парсер данных с сайта с сохранением в SQLite.",
        published_at=datetime.now(UTC),
        budget=15000,
        currency="RUB",
        tags=["Python", "Парсинг"],
        source="habr",
    )

    await temp_db.save_order(order)
    cached = await temp_db.get_order("habr_12345")

    assert cached is not None
    assert cached.id == "habr_12345"
    assert cached.title == "Скрипт парсинга на Python"
    assert cached.budget == 15000
    assert "Python" in cached.tags


@pytest.mark.asyncio
async def test_get_active_subscribers(temp_db: Database):
    """Verify gathering active subscribers with their respective keywords."""
    p1 = FreelancerProfile(telegram_id=10, full_name="Active 1", is_active=True)
    p2 = FreelancerProfile(telegram_id=20, full_name="Paused 2", is_active=False)
    await temp_db.upsert_user(p1)
    await temp_db.upsert_user(p2)

    await temp_db.add_keyword(10, "aiogram")
    await temp_db.add_keyword(10, "php", is_negative=True)

    subscribers = await temp_db.get_active_subscribers()
    assert len(subscribers) == 1

    sub_profile, positives, negatives = subscribers[0]
    assert sub_profile.telegram_id == 10
    assert positives == ["aiogram"]
    assert negatives == ["php"]
