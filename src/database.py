"""Async SQLite database storage for Gig Sentinel using aiosqlite."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from src.models import FreelanceOrder, FreelancerProfile


class Database:
    """Async database layer for managing users, keywords, deduplication, and order cache."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        """Open database connection and configure WAL mode for high concurrency."""
        if self._connection is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = await aiosqlite.connect(self.db_path)
            self._connection.row_factory = aiosqlite.Row
            await self._connection.execute("PRAGMA journal_mode = WAL;")
            await self._connection.execute("PRAGMA foreign_keys = ON;")
        return self._connection

    async def close(self) -> None:
        """Close database connection."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def __aenter__(self) -> "Database":
        await self.connect()
        await self.init_db()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()

    async def init_db(self) -> None:
        """Create database tables and indexes if they do not exist."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            # Users table
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    specialization TEXT NOT NULL,
                    skills TEXT NOT NULL,
                    experience_years INTEGER NOT NULL DEFAULT 1,
                    portfolio_url TEXT,
                    hourly_rate INTEGER,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            # User keywords filter table
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                    keyword TEXT NOT NULL,
                    is_negative INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, keyword, is_negative)
                )
                """
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_keywords_user_id ON user_keywords(user_id);"
            )

            # Seen orders table for strict deduplication
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_orders (
                    order_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                    seen_at TEXT NOT NULL,
                    is_notified INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (order_id, user_id)
                )
                """
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_seen_orders_user ON seen_orders(user_id, order_id);"
            )

            # Cached orders table
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS cached_orders (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    description TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    budget INTEGER,
                    currency TEXT NOT NULL,
                    is_negotiable INTEGER NOT NULL DEFAULT 0,
                    tags TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        await conn.commit()

    # -------------------------------------------------------------------------
    # USER PROFILE OPERATIONS
    # -------------------------------------------------------------------------

    async def upsert_user(self, profile: FreelancerProfile) -> FreelancerProfile:
        """Create or update a freelancer profile."""
        conn = await self.connect()
        now_iso = datetime.now(UTC).isoformat()
        skills_json = json.dumps(profile.skills, ensure_ascii=False)

        await conn.execute(
            """
            INSERT INTO users (
                telegram_id, username, full_name, specialization,
                skills, experience_years, portfolio_url, hourly_rate,
                is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                specialization = excluded.specialization,
                skills = excluded.skills,
                experience_years = excluded.experience_years,
                portfolio_url = excluded.portfolio_url,
                hourly_rate = excluded.hourly_rate,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
            """,
            (
                profile.telegram_id,
                profile.username,
                profile.full_name,
                profile.specialization,
                skills_json,
                profile.experience_years,
                profile.portfolio_url,
                profile.hourly_rate,
                1 if profile.is_active else 0,
                profile.created_at.isoformat(),
                now_iso,
            ),
        )
        await conn.commit()
        return profile

    async def get_user(self, telegram_id: int) -> FreelancerProfile | None:
        """Retrieve user profile by Telegram ID."""
        conn = await self.connect()
        async with conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            return FreelancerProfile(
                telegram_id=row["telegram_id"],
                username=row["username"],
                full_name=row["full_name"],
                specialization=row["specialization"],
                skills=json.loads(row["skills"]),
                experience_years=row["experience_years"],
                portfolio_url=row["portfolio_url"],
                hourly_rate=row["hourly_rate"],
                is_active=bool(row["is_active"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    async def set_user_active(self, telegram_id: int, is_active: bool) -> bool:
        """Toggle active notification status for user."""
        conn = await self.connect()
        now_iso = datetime.now(UTC).isoformat()
        cursor = await conn.execute(
            "UPDATE users SET is_active = ?, updated_at = ? WHERE telegram_id = ?",
            (1 if is_active else 0, now_iso, telegram_id),
        )
        await conn.commit()
        return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # KEYWORDS & FILTERS OPERATIONS
    # -------------------------------------------------------------------------

    async def add_keyword(self, user_id: int, keyword: str, is_negative: bool = False) -> bool:
        """Add positive or negative keyword for user. Returns True if newly added."""
        clean_keyword = keyword.strip().lower()
        if not clean_keyword:
            return False

        conn = await self.connect()
        now_iso = datetime.now(UTC).isoformat()
        try:
            await conn.execute(
                """
                INSERT INTO user_keywords (user_id, keyword, is_negative, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, clean_keyword, 1 if is_negative else 0, now_iso),
            )
            await conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_keyword(self, user_id: int, keyword: str) -> bool:
        """Remove a keyword (positive or negative) for user."""
        clean_keyword = keyword.strip().lower()
        conn = await self.connect()
        cursor = await conn.execute(
            "DELETE FROM user_keywords WHERE user_id = ? AND keyword = ?",
            (user_id, clean_keyword),
        )
        await conn.commit()
        return cursor.rowcount > 0

    async def get_user_keywords(self, user_id: int) -> tuple[list[str], list[str]]:
        """Return (positive_keywords, negative_keywords) for user."""
        conn = await self.connect()
        async with conn.execute(
            "SELECT keyword, is_negative FROM user_keywords WHERE user_id = ? ORDER BY keyword ASC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            positives: list[str] = []
            negatives: list[str] = []
            for row in rows:
                if row["is_negative"]:
                    negatives.append(row["keyword"])
                else:
                    positives.append(row["keyword"])
            return positives, negatives

    async def clear_keywords(self, user_id: int) -> int:
        """Delete all keywords for user."""
        conn = await self.connect()
        cursor = await conn.execute(
            "DELETE FROM user_keywords WHERE user_id = ?",
            (user_id,),
        )
        await conn.commit()
        return cursor.rowcount

    # -------------------------------------------------------------------------
    # DEDUPLICATION & SEEN ORDERS
    # -------------------------------------------------------------------------

    async def is_order_seen(self, order_id: str, user_id: int) -> bool:
        """Check if order was already delivered/seen by this user."""
        conn = await self.connect()
        async with conn.execute(
            "SELECT 1 FROM seen_orders WHERE order_id = ? AND user_id = ?",
            (order_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def mark_order_seen(
        self,
        order_id: str,
        user_id: int,
        is_notified: bool = True,
    ) -> bool:
        """Record order as delivered/seen for this user. Returns True if new."""
        conn = await self.connect()
        now_iso = datetime.now(UTC).isoformat()
        try:
            await conn.execute(
                """
                INSERT INTO seen_orders (order_id, user_id, seen_at, is_notified)
                VALUES (?, ?, ?, ?)
                """,
                (order_id, user_id, now_iso, 1 if is_notified else 0),
            )
            await conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    # -------------------------------------------------------------------------
    # ORDER CACHE
    # -------------------------------------------------------------------------

    async def save_order(self, order: FreelanceOrder) -> None:
        """Cache order details for interactive actions like AI pitch generation."""
        conn = await self.connect()
        now_iso = datetime.now(UTC).isoformat()
        tags_json = json.dumps(order.tags, ensure_ascii=False)

        await conn.execute(
            """
            INSERT INTO cached_orders (
                id, title, url, description, published_at,
                budget, currency, is_negotiable, tags, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                url = excluded.url,
                description = excluded.description,
                budget = excluded.budget,
                currency = excluded.currency,
                is_negotiable = excluded.is_negotiable,
                tags = excluded.tags
            """,
            (
                order.id,
                order.title,
                order.url,
                order.description,
                order.published_at.isoformat(),
                order.budget,
                order.currency,
                1 if order.is_negotiable else 0,
                tags_json,
                order.source,
                now_iso,
            ),
        )
        await conn.commit()

    async def get_order(self, order_id: str) -> FreelanceOrder | None:
        """Retrieve cached order by ID."""
        conn = await self.connect()
        async with conn.execute(
            "SELECT * FROM cached_orders WHERE id = ?",
            (order_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            return FreelanceOrder(
                id=row["id"],
                title=row["title"],
                url=row["url"],
                description=row["description"],
                published_at=datetime.fromisoformat(row["published_at"]),
                budget=row["budget"],
                currency=row["currency"],
                is_negotiable=bool(row["is_negotiable"]),
                tags=json.loads(row["tags"]),
                source=row["source"],
            )

    # -------------------------------------------------------------------------
    # SUBSCRIBERS AGGREGATION
    # -------------------------------------------------------------------------

    async def get_active_subscribers(
        self,
    ) -> list[tuple[FreelancerProfile, list[str], list[str]]]:
        """Fetch all active users paired with their (positives, negatives) keyword lists."""
        conn = await self.connect()
        async with conn.execute(
            "SELECT * FROM users WHERE is_active = 1",
        ) as cursor:
            user_rows = await cursor.fetchall()

        subscribers: list[tuple[FreelancerProfile, list[str], list[str]]] = []
        for row in user_rows:
            profile = FreelancerProfile(
                telegram_id=row["telegram_id"],
                username=row["username"],
                full_name=row["full_name"],
                specialization=row["specialization"],
                skills=json.loads(row["skills"]),
                experience_years=row["experience_years"],
                portfolio_url=row["portfolio_url"],
                hourly_rate=row["hourly_rate"],
                is_active=bool(row["is_active"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            positives, negatives = await self.get_user_keywords(profile.telegram_id)
            subscribers.append((profile, positives, negatives))

        return subscribers
