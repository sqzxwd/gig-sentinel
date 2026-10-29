"""Unit tests for RSS parsing, HTML normalization, and keyword filtering."""

from datetime import UTC, datetime

import pytest
import respx

from src.models import FreelanceOrder
from src.parser import (
    HabrFreelanceParser,
    clean_html,
    matches_keywords,
    parse_order_budget,
    parse_pub_date,
    parse_rss_xml,
)

SAMPLE_HABR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Хабр Фриланс: Заказы</title>
    <link>https://freelance.habr.com/tasks</link>
    <description>Лента заказов на Хабр Фриланс</description>
    <item>
      <title>Разработка бота для Telegram на aiogram 3 (30 000 руб.)</title>
      <link>https://freelance.habr.com/tasks/987654</link>
      <guid>https://freelance.habr.com/tasks/987654</guid>
      <description><![CDATA[<p>Требуется разработать Telegram-бота на <b>Python 3.14</b> с базой данных <i>SQLite</i>.</p><p>Бюджет: 30 000 руб.</p>]]></description>
      <pubDate>Thu, 29 Oct 2026 12:00:00 +0300</pubDate>
      <category>Разработка ботов</category>
      <category>Python</category>
    </item>
    <item>
      <title>Верстка лендинга на WordPress</title>
      <link>https://freelance.habr.com/tasks/987655</link>
      <guid>https://freelance.habr.com/tasks/987655</guid>
      <description><![CDATA[Нужна верстка на HTML/CSS и натяжка на WordPress. Цена по договоренности.]]></description>
      <pubDate>Thu, 29 Oct 2026 13:00:00 +0300</pubDate>
      <category>Верстка</category>
      <category>WordPress</category>
    </item>
  </channel>
</rss>
"""


def test_clean_html():
    """Verify stripping tags and unescaping entities."""
    raw = "<p>Привет &amp; добро пожаловать! <a href='https://example.com'>Ссылка</a><br/></p>"
    cleaned = clean_html(raw)
    assert cleaned == "Привет & добро пожаловать! Ссылка"


def test_parse_order_budget():
    """Verify budget and negotiation status extraction."""
    budget, curr, is_neg = parse_order_budget("Разработка сервиса", "Оплата 45 000 руб.")
    assert budget == 45000
    assert curr == "RUB"
    assert is_neg is False

    budget2, _curr2, is_neg2 = parse_order_budget("Дизайн баннеров", "Цена по договоренности")
    assert budget2 is None
    assert is_neg2 is True


def test_parse_pub_date():
    """Verify RFC date parsing to UTC datetime."""
    dt = parse_pub_date("Thu, 29 Oct 2026 12:00:00 +0300")
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 29
    assert dt.tzinfo == UTC


def test_parse_rss_xml():
    """Verify parsing full RSS XML payload into FreelanceOrder objects."""
    orders = parse_rss_xml(SAMPLE_HABR_RSS)
    assert len(orders) == 2

    first = orders[0]
    assert first.id == "habr_987654"
    assert "aiogram" in first.title
    assert first.budget == 30000
    assert "Python" in first.tags
    assert "<p>" not in first.description
    assert first.url == "https://freelance.habr.com/tasks/987654"

    second = orders[1]
    assert second.id == "habr_987655"
    assert second.is_negotiable is True
    assert "WordPress" in second.tags


def test_matches_keywords():
    """Verify positive and negative filtering logic."""
    order = FreelanceOrder(
        id="habr_1",
        title="Разработка Telegram-бота на Python и aiogram",
        url="https://freelance.habr.com/tasks/1",
        description="Необходимо интегрировать OpenAI API и платежный шлюз.",
        published_at=datetime.now(UTC),
        tags=["Python", "Чат-боты"],
    )

    # Positive match
    assert matches_keywords(order, positive_keywords=["python"]) is True
    assert matches_keywords(order, positive_keywords=["openai"]) is True
    assert matches_keywords(order, positive_keywords=["чат-боты"]) is True

    # No match
    assert matches_keywords(order, positive_keywords=["golang", "react"]) is False

    # Negative filter (stop-word) overrides positive match
    assert (
        matches_keywords(
            order,
            positive_keywords=["python"],
            negative_keywords=["openai"],
        )
        is False
    )

    # Empty positive list accepts all (when not excluded by negative)
    assert matches_keywords(order, positive_keywords=[]) is True
    assert matches_keywords(order, positive_keywords=[], negative_keywords=["php"]) is True
    assert matches_keywords(order, positive_keywords=[], negative_keywords=["aiogram"]) is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_orders_with_network_mock():
    """Verify async fetch_orders successfully parses orders from mocked HTTP response."""
    feed_url = "https://freelance.habr.com/tasks.rss"
    respx.get(feed_url).respond(
        status_code=200,
        text=SAMPLE_HABR_RSS,
        headers={"Content-Type": "application/rss+xml"},
    )

    parser = HabrFreelanceParser(rss_url=feed_url)
    orders = await parser.fetch_orders()

    assert len(orders) == 2
    assert orders[0].id == "habr_987654"
    assert orders[1].id == "habr_987655"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_orders_handles_http_error():
    """Verify parser safely returns empty list on network error."""
    feed_url = "https://freelance.habr.com/tasks.rss"
    respx.get(feed_url).respond(status_code=500)

    parser = HabrFreelanceParser(rss_url=feed_url)
    orders = await parser.fetch_orders()
    assert orders == []
