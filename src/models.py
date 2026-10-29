"""Pydantic data models for Gig Sentinel domain."""

import html
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class FreelanceOrder(BaseModel):
    """Normalized freelance project/order from RSS feeds."""

    id: str = Field(description="Unique identifier (e.g. habr_123456)")
    title: str = Field(description="Task title")
    url: str = Field(description="Direct link to task page")
    description: str = Field(description="Sanitized task description")
    published_at: datetime = Field(description="Task publication timestamp")
    budget: int | None = Field(default=None, description="Budget in currency units, if specified")
    currency: str = Field(default="RUB", description="Currency symbol or ISO code")
    is_negotiable: bool = Field(
        default=False, description="Whether price is negotiable/contractual"
    )
    tags: list[str] = Field(default_factory=list, description="Skill/category tags")
    source: str = Field(default="habr", description="Source aggregator (e.g. habr, fl, kwork)")

    @property
    def formatted_budget(self) -> str:
        """User-friendly budget representation."""
        if self.budget is not None and self.budget > 0:
            return f"{self.budget:,} {self.currency}".replace(",", " ")
        if self.is_negotiable:
            return "Договорная"
        return "Не указан"

    def to_telegram_html(self) -> str:
        """Format order as safe HTML for Telegram bot messages."""
        safe_title = html.escape(self.title)
        safe_url = html.escape(self.url)
        tags_str = " ".join(f"#{tag.replace(' ', '_').replace('-', '_')}" for tag in self.tags)
        snippet = self.description[:350].strip()
        if len(self.description) > 350:
            snippet += "..."
        safe_snippet = html.escape(snippet)

        lines = [
            f"🔔 <b>Новый заказ: <a href='{safe_url}'>{safe_title}</a></b>",
            "",
            f"💰 <b>Бюджет:</b> {html.escape(self.formatted_budget)}",
            f"🏷 <b>Категории:</b> {html.escape(tags_str) if tags_str else '<i>без тегов</i>'}",
            "",
            f"📝 <b>Описание:</b>\n{safe_snippet}",
        ]
        return "\n".join(lines)


class FreelancerProfile(BaseModel):
    """Freelancer professional profile used for AI pitch context and user settings."""

    telegram_id: int = Field(description="Telegram user ID")
    username: str | None = Field(default=None, description="Telegram username without @")
    full_name: str = Field(default="Фрилансер", description="User display name")
    specialization: str = Field(
        default="Python Backend & AI Developer",
        description="Core specialization or title",
    )
    skills: list[str] = Field(
        default_factory=lambda: ["Python", "FastAPI", "PostgreSQL", "Telegram Bots", "AI"],
        description="List of core professional competencies",
    )
    experience_years: int = Field(
        default=3,
        ge=0,
        description="Years of professional experience",
    )
    portfolio_url: str | None = Field(
        default=None,
        description="Link to GitHub, personal site or portfolio",
    )
    hourly_rate: int | None = Field(
        default=None,
        ge=0,
        description="Hourly rate in RUB or USD",
    )
    is_active: bool = Field(
        default=True,
        description="Whether user actively receives new order alerts",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Registration timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last update timestamp",
    )

    def to_telegram_card(self, keywords_count: int = 0) -> str:
        """Format profile as readable summary card for Telegram."""
        safe_name = html.escape(self.full_name)
        safe_spec = html.escape(self.specialization)
        skills_str = html.escape(", ".join(self.skills) if self.skills else "не указаны")
        status = "🟢 Активен (уведомления включены)" if self.is_active else "🔴 На паузе"
        rate_str = (
            f"{self.hourly_rate:,} руб./час".replace(",", " ") if self.hourly_rate else "не указана"
        )
        portfolio = (
            f"<a href='{html.escape(self.portfolio_url)}'>{html.escape(self.portfolio_url)}</a>"
            if self.portfolio_url
            else "не указано"
        )

        return (
            f"👤 <b>Профиль фрилансера: {safe_name}</b>\n\n"
            f"💼 <b>Специализация:</b> {safe_spec}\n"
            f"⏳ <b>Опыт:</b> {self.experience_years} лет/года\n"
            f"🛠 <b>Навыки:</b> {skills_str}\n"
            f"💵 <b>Ставка:</b> {rate_str}\n"
            f"🌐 <b>Портфолио:</b> {portfolio}\n"
            f"🔍 <b>Активных фильтров:</b> {keywords_count}\n"
            f"📡 <b>Статус бота:</b> {status}"
        )


class PitchResponse(BaseModel):
    """Structured AI pitch response generated for a specific freelance order."""

    order_id: str = Field(description="Referenced order ID")
    subject: str = Field(description="Short, high-converting hook/headline")
    pitch_text: str = Field(description="Main body of commercial proposal")
    relevant_skills: list[str] = Field(
        default_factory=list,
        description="Key skills highlighted for this specific project",
    )
    estimated_duration: str | None = Field(
        default=None,
        description="Estimated project delivery time",
    )
    estimated_cost: str | None = Field(
        default=None,
        description="Estimated cost or proposed budget",
    )
    call_to_action: str = Field(
        default="Готов обсудить детали в чате или созвоне.",
        description="Direct closing CTA",
    )

    def to_telegram_message(self, order_title: str) -> str:
        """Render proposal ready for user review and 1-click copying."""
        safe_title = html.escape(order_title)
        safe_subject = html.escape(self.subject)
        safe_pitch = html.escape(self.pitch_text)
        safe_cta = html.escape(self.call_to_action)
        safe_time = html.escape(self.estimated_duration or "По согласованию")
        safe_cost = html.escape(self.estimated_cost or "В рамках бюджета")
        skills_str = html.escape(", ".join(self.relevant_skills)) if self.relevant_skills else ""

        lines = [
            f"✨ <b>Коммерческий отклик на заказ:</b> <i>{safe_title}</i>",
            "",
            f"🎯 <b>Хук:</b> {safe_subject}",
            "",
            f"📝 <b>Текст предложения:</b>\n{safe_pitch}",
            "",
            f"⏱ <b>Срок:</b> {safe_time} | 💰 <b>Оценка:</b> {safe_cost}",
        ]
        if skills_str:
            lines.append(f"🛠 <b>Фокус на технологиях:</b> {skills_str}")
        lines.extend(
            [
                f"🤝 <b>CTA:</b> {safe_cta}",
                "",
                "💡 <i>Скопируйте текст выше и отправьте заказчику на бирже!</i>",
            ]
        )
        return "\n".join(lines)
