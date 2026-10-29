"""AI Pitch Generator using prompt engineering for commercial freelance proposals."""

import json
import logging
import re

import httpx

from src.config import Settings
from src.config import settings as default_settings
from src.models import FreelanceOrder, FreelancerProfile, PitchResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — ведущий эксперт по коммерческим B2B-продажам и откликам на фриланс-биржах.
Твоя цель — сформировать персонализированный, высококонверсионный отклик на проект заказчика.

ЗОЛОТЫЕ ПРАВИЛА КОММЕРЧЕСКОГО ОТКЛИКА:
1. НИКАКОЙ ВОДЫ И ШАБЛОНОВ. Запрещены фразы вроде: "Здравствуйте, меня заинтересовал ваш заказ", "Я опытный специалист широкого профиля".
2. ХУК (С первого предложения): Сразу покажи понимание сути задачи заказчика и ключевой проблемы.
3. РЕШЕНИЕ: Предложи конкретный стек, архитектурный подход или план реализации из 2-3 ключевых шагов.
4. РЕЛЕВАНТНЫЙ ОПЫТ: Упомяни 1-2 похожие задачи или технологии из профиля фрилансера.
5. СРОКИ И ОЦЕНКА: Дай адекватную предварительную оценку по времени и готовность обсудить бюджет.
6. CTA (Call To Action): Четкий и легкий следующий шаг (например: "Готовы созвониться на 10 минут или обсудить ТЗ в чате?").

ФОРМАТ ОТВЕТА (ТОЛЬКО ЧИСТЫЙ JSON):
{
  "subject": "Короткий заголовок-хук с фокусом на результат",
  "pitch_text": "Основной продающий текст отклика (3-4 абзаца с абзацными отступами)",
  "relevant_skills": ["Скилл 1", "Скилл 2"],
  "estimated_duration": "Оценка срока (например: '3-5 рабочих дней')",
  "estimated_cost": "Оценка бюджета (например: '25 000 - 30 000 руб.' или 'В рамках указанного бюджета')",
  "call_to_action": "Призыв к действию"
}
"""


def build_pitch_prompt(order: FreelanceOrder, profile: FreelancerProfile) -> str:
    """Compose structured context and instructions for the LLM."""
    skills_list = ", ".join(profile.skills)
    tags_list = ", ".join(order.tags) if order.tags else "не указаны"
    budget_info = order.formatted_budget

    return f"""ДАННЫЕ ЗАКАЗА:
- Название: {order.title}
- Категории / Теги: {tags_list}
- Бюджет заказчика: {budget_info}
- Полное ТЗ / Описание:
{order.description}

ДАННЫЕ ФРИЛАНСЕРА:
- Имя: {profile.full_name}
- Специализация: {profile.specialization}
- Опыт: {profile.experience_years} года/лет
- Ключевые навыки: {skills_list}
- Ставка: {profile.hourly_rate or "по договоренности"}
- Портфолио: {profile.portfolio_url or "предоставляется по запросу"}

Сгенерируй коммерческий отклик строго в формате JSON."""


def generate_fallback_pitch(order: FreelanceOrder, profile: FreelancerProfile) -> PitchResponse:
    """Generate high-quality rule-based proposal when LLM API is unavailable or disabled."""
    order_lower = f"{order.title} {order.description}".lower()
    matched_skills = [s for s in profile.skills if s.lower() in order_lower]
    if not matched_skills:
        matched_skills = profile.skills[:3]

    primary_skill = matched_skills[0] if matched_skills else "Python"
    budget_estimate = order.formatted_budget if order.budget else "В рамках вашего бюджета"

    # Commercial hook
    subject = f"Реализация задачи «{order.title[:45]}...» на стеке {primary_skill}"

    portfolio_mention = (
        f" С примерами аналогичных работ можно ознакомиться в моем портфолио: {profile.portfolio_url}."
        if profile.portfolio_url
        else ""
    )

    body_paragraphs = [
        f"Здравствуйте! Ознакомился с вашим техническим заданием: «{order.title}». Задача понятна, готов подключиться к реализации.",
        f"В качестве основного решения предлагаю использовать современный надежный стек на базе {', '.join(matched_skills[:3])}. Обеспечу чистую архитектуру, покрытие тестами и быструю интеграцию без скрытых переделок в будущем.",
        f"Мой опыт в коммерческой разработке — более {profile.experience_years} лет.{portfolio_mention}",
        "Предлагаю провести короткий созвон или обсудить детали ТЗ в переписке, чтобы составить точный план этапов и зафиксировать сроки.",
    ]

    return PitchResponse(
        order_id=order.id,
        subject=subject,
        pitch_text="\n\n".join(body_paragraphs),
        relevant_skills=matched_skills[:4],
        estimated_duration="2-5 рабочих дней (уточняется по ТЗ)",
        estimated_cost=budget_estimate,
        call_to_action="Напишите в ответ, и мы согласуем финальные требования и старт работы.",
    )


def extract_json_payload(response_text: str) -> dict:
    """Robustly extract JSON object from LLM response containing markdown codeblocks."""
    clean_text = response_text.strip()
    # Match ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_text, re.DOTALL)
    if match:
        clean_text = match.group(1)
    else:
        # Fallback to finding first { and last }
        start = clean_text.find("{")
        end = clean_text.rfind("}")
        if start != -1 and end != -1:
            clean_text = clean_text[start : end + 1]

    return json.loads(clean_text)


class AIPitcher:
    """Engine for generating customized commercial pitches for freelance orders."""

    def __init__(self, config: Settings = default_settings) -> None:
        self.config = config

    async def generate_pitch(
        self,
        order: FreelanceOrder,
        profile: FreelancerProfile,
        client: httpx.AsyncClient | None = None,
    ) -> PitchResponse:
        """
        Generate commercial proposal.

        Uses LLM API if key is configured, otherwise gracefully falls back
        to intelligent deterministic template generation.
        """
        if not self.config.is_ai_configured:
            logger.info(
                "AI API key not provided. Using intelligent template engine for order %s", order.id
            )
            return generate_fallback_pitch(order, profile)

        api_key = self.config.ai_api_key.get_secret_value() if self.config.ai_api_key else ""
        user_prompt = build_pitch_prompt(order, profile)

        # Gemini API standard payload
        url = f"{self.config.ai_api_base_url}/models/{self.config.ai_model}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{SYSTEM_PROMPT}\n\n{user_prompt}"}],
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "responseMimeType": "application/json",
            },
        }

        try:
            if client is not None:
                response = await client.post(
                    url,
                    json=payload,
                    timeout=self.config.request_timeout,
                )
                response.raise_for_status()
                data = response.json()
            else:
                async with httpx.AsyncClient(timeout=self.config.request_timeout) as local_client:
                    response = await local_client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()

            # Parse Gemini candidate response
            candidate_text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed_json = extract_json_payload(candidate_text)

            return PitchResponse(
                order_id=order.id,
                subject=parsed_json.get("subject", f"Отклик на: {order.title}"),
                pitch_text=parsed_json.get("pitch_text", ""),
                relevant_skills=parsed_json.get("relevant_skills", profile.skills[:3]),
                estimated_duration=parsed_json.get("estimated_duration"),
                estimated_cost=parsed_json.get("estimated_cost"),
                call_to_action=parsed_json.get(
                    "call_to_action",
                    "Готов обсудить детали в чате или созвоне.",
                ),
            )

        except Exception as exc:
            logger.warning(
                "AI generation failed for order %s (%s). Falling back to template generator.",
                order.id,
                exc,
            )
            return generate_fallback_pitch(order, profile)
