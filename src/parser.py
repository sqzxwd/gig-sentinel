"""Async Habr Freelance RSS collector and keyword matching engine using httpx."""

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from pydantic import HttpUrl

from src.models import FreelanceOrder

logger = logging.getLogger(__name__)

# Regular expressions for data cleaning and budget parsing
HTML_TAGS_PATTERN = re.compile(r"<[^>]+>")
TASK_ID_PATTERN = re.compile(r"/tasks/(\d+)")
BUDGET_DIGITS_PATTERN = re.compile(r"(\d[\d\s]{2,})\s*(?:руб|₽|rub)", re.IGNORECASE)
NEGOTIABLE_PATTERN = re.compile(r"договорн|по договоренности", re.IGNORECASE)


def clean_html(raw_html: str) -> str:
    """Strip HTML tags, unescape HTML entities, and normalize whitespace."""
    if not raw_html:
        return ""
    text_without_tags = HTML_TAGS_PATTERN.sub(" ", raw_html)
    unescaped = html.unescape(text_without_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def parse_order_budget(title: str, description: str) -> tuple[int | None, str, bool]:
    """Extract budget amount, currency, and negotiable flag from title/description."""
    combined_text = f"{title} {description}"

    # Search for numeric budget in RUB
    match = BUDGET_DIGITS_PATTERN.search(combined_text)
    if match:
        raw_digits = re.sub(r"\s+", "", match.group(1))
        try:
            return int(raw_digits), "RUB", False
        except ValueError:
            pass

    # Check negotiable
    if NEGOTIABLE_PATTERN.search(combined_text):
        return None, "RUB", True

    return None, "RUB", False


def parse_pub_date(pub_date_str: str | None) -> datetime:
    """Parse RFC 822 / 2822 RSS date string into UTC datetime."""
    if not pub_date_str:
        return datetime.now(UTC)
    try:
        dt = parsedate_to_datetime(pub_date_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return datetime.now(UTC)


def parse_rss_xml(xml_content: str) -> list[FreelanceOrder]:
    """Parse RSS 2.0 XML string into a list of validated FreelanceOrder models."""
    root = ET.fromstring(xml_content)
    orders: list[FreelanceOrder] = []

    # Iterate over all <item> elements in RSS channel
    for item in root.findall(".//item"):
        title_elem = item.find("title")
        link_elem = item.find("link")
        guid_elem = item.find("guid")
        desc_elem = item.find("description")
        pub_date_elem = item.find("pubDate")
        category_elems = item.findall("category")

        title = clean_html(title_elem.text if title_elem is not None and title_elem.text else "")
        link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
        guid = guid_elem.text.strip() if guid_elem is not None and guid_elem.text else link
        raw_description = desc_elem.text if desc_elem is not None and desc_elem.text else ""
        description = clean_html(raw_description)

        if not title or not link:
            continue

        # Extract stable Habr Task ID
        id_match = TASK_ID_PATTERN.search(link) or TASK_ID_PATTERN.search(guid)
        order_id = f"habr_{id_match.group(1)}" if id_match else f"habr_{abs(hash(link))}"

        # Extract tags
        tags = [cat.text.strip() for cat in category_elems if cat.text and cat.text.strip()]

        # Extract budget and negotiable status
        budget, currency, is_negotiable = parse_order_budget(title, description)
        published_at = parse_pub_date(pub_date_elem.text if pub_date_elem is not None else None)

        orders.append(
            FreelanceOrder(
                id=order_id,
                title=title,
                url=link,
                description=description,
                published_at=published_at,
                budget=budget,
                currency=currency,
                is_negotiable=is_negotiable,
                tags=tags,
                source="habr",
            )
        )

    return orders


def matches_keywords(
    order: FreelanceOrder,
    positive_keywords: list[str],
    negative_keywords: list[str] | None = None,
) -> bool:
    """
    Check if a freelance order matches user keyword criteria.

    - If any negative keyword is found in title, description or tags -> Rejected (False).
    - If positive_keywords is empty -> Accepted (True).
    - If positive_keywords is non-empty -> Accepted (True) if ANY keyword is found.
    """
    searchable_text = f"{order.title} {order.description} {' '.join(order.tags)}".lower()

    # 1. Negative filter check
    if negative_keywords:
        for neg in negative_keywords:
            neg_clean = neg.strip().lower()
            if neg_clean and neg_clean in searchable_text:
                return False

    # 2. Positive filter check
    clean_positives = [p.strip().lower() for p in positive_keywords if p.strip()]
    if not clean_positives:
        # If no positive filters defined, matches all
        return True

    return any(keyword in searchable_text for keyword in clean_positives)


class HabrFreelanceParser:
    """Async RSS fetcher and parser for Habr Freelance."""

    def __init__(
        self,
        rss_url: HttpUrl | str = "https://freelancehunt.com/projects.rss",
        timeout: float = 15.0,
    ) -> None:
        self.rss_url = str(rss_url)
        self.timeout = timeout

    async def fetch_orders(
        self,
        client: httpx.AsyncClient | None = None,
    ) -> list[FreelanceOrder]:
        """Fetch latest orders from Habr Freelance RSS."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; GigSentinel/0.1; +https://github.com/gig-sentinel)"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }

        try:
            if client is not None:
                response = await client.get(self.rss_url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                return parse_rss_xml(response.text)

            async with httpx.AsyncClient(timeout=self.timeout) as local_client:
                response = await local_client.get(
                    self.rss_url,
                    headers=headers,
                )
                response.raise_for_status()
                return parse_rss_xml(response.text)

        except httpx.HTTPError as exc:
            logger.error("HTTP error while fetching Habr Freelance RSS: %s", exc)
            return []
        except ET.ParseError as exc:
            logger.error("XML parse error on Habr Freelance RSS: %s", exc)
            return []
        except Exception as exc:
            logger.exception("Unexpected error in HabrFreelanceParser: %s", exc)
            return []


if __name__ == "__main__":
    import asyncio

    async def _run():
        parser = HabrFreelanceParser()
        orders = await parser.fetch_orders()
        print(f"\n✅ успешно получено заказов: {len(orders)}\n")
        for i, o in enumerate(orders[:5], 1):
            budget = getattr(o, "budget", None) or "по договоренности"
            print(f"{i}. {o.title}")
            print(f"   бюджет: {budget}")
            print(f"   ссылка: {o.url}\n")

    asyncio.run(_run())
