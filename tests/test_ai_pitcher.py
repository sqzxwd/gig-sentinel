"""Unit tests for AI pitch generator, prompt construction, and mock API handling."""

from datetime import UTC, datetime

import pytest
import respx
from pydantic import SecretStr

from src.ai_pitcher import (
    AIPitcher,
    build_pitch_prompt,
    extract_json_payload,
    generate_fallback_pitch,
)
from src.config import Settings
from src.models import FreelanceOrder, FreelancerProfile, PitchResponse


@pytest.fixture
def sample_order() -> FreelanceOrder:
    return FreelanceOrder(
        id="habr_555",
        title="Разработка асинхронного сервиса на FastAPI",
        url="https://freelance.habr.com/tasks/555",
        description="Необходимо разработать REST API сервис для обработки платежей с базой PostgreSQL.",
        published_at=datetime.now(UTC),
        budget=40000,
        currency="RUB",
        tags=["Python", "FastAPI", "PostgreSQL"],
    )


@pytest.fixture
def sample_profile() -> FreelancerProfile:
    return FreelancerProfile(
        telegram_id=999,
        full_name="Алексей Смирнов",
        specialization="Senior Python & Backend Engineer",
        skills=["Python", "FastAPI", "PostgreSQL", "Docker", "aiogram"],
        experience_years=4,
        portfolio_url="https://github.com/alexey-smirnov",
        hourly_rate=2000,
    )


def test_build_pitch_prompt(sample_order: FreelanceOrder, sample_profile: FreelancerProfile):
    """Verify prompt includes essential order and profile details."""
    prompt = build_pitch_prompt(sample_order, sample_profile)
    assert sample_order.title in prompt
    assert sample_profile.full_name in prompt
    assert "FastAPI" in prompt
    assert "40 000 RUB" in prompt


def test_generate_fallback_pitch(sample_order: FreelanceOrder, sample_profile: FreelancerProfile):
    """Verify fallback proposal generation produces high-quality pitch."""
    pitch = generate_fallback_pitch(sample_order, sample_profile)
    assert isinstance(pitch, PitchResponse)
    assert pitch.order_id == "habr_555"
    assert "FastAPI" in pitch.subject
    assert sample_profile.portfolio_url in pitch.pitch_text
    assert len(pitch.relevant_skills) > 0
    assert pitch.call_to_action != ""


def test_extract_json_payload():
    """Verify extracting json from raw string and markdown codeblock."""
    raw_block = """Here is the response:
```json
{
  "subject": "Решение вашей задачи",
  "pitch_text": "Предлагаю качественную реализацию.",
  "relevant_skills": ["Python", "FastAPI"],
  "estimated_duration": "3 дня",
  "estimated_cost": "35000 руб",
  "call_to_action": "Давайте созвонимся"
}
```
Hope this helps!"""

    payload = extract_json_payload(raw_block)
    assert payload["subject"] == "Решение вашей задачи"
    assert payload["relevant_skills"] == ["Python", "FastAPI"]


@pytest.mark.asyncio
@respx.mock
async def test_ai_pitcher_api_call(sample_order: FreelanceOrder, sample_profile: FreelancerProfile):
    """Verify API request and response parsing using mocked LLM endpoint."""
    config = Settings(
        ai_api_key=SecretStr("test_secret_key"),
        ai_api_base_url="https://mock-ai.example.com/v1",
        ai_model="test-model",
    )
    pitcher = AIPitcher(config=config)

    mock_llm_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                "{\n"
                                '  "subject": "Быстрый запуск FastAPI сервиса",\n'
                                '  "pitch_text": "Готов разработать отказоустойчивое API с чистой архитектурой.",\n'
                                '  "relevant_skills": ["FastAPI", "PostgreSQL"],\n'
                                '  "estimated_duration": "4 рабочих дня",\n'
                                '  "estimated_cost": "40 000 руб.",\n'
                                '  "call_to_action": "Жду вас в личных сообщениях для уточнения деталей."\n'
                                "}"
                            )
                        }
                    ]
                }
            }
        ]
    }

    respx.post("https://mock-ai.example.com/v1/models/test-model:generateContent").respond(
        status_code=200,
        json=mock_llm_response,
    )

    pitch = await pitcher.generate_pitch(sample_order, sample_profile)
    assert pitch.order_id == sample_order.id
    assert pitch.subject == "Быстрый запуск FastAPI сервиса"
    assert "FastAPI" in pitch.relevant_skills
    assert pitch.estimated_duration == "4 рабочих дня"


@pytest.mark.asyncio
@respx.mock
async def test_ai_pitcher_fallback_on_api_error(
    sample_order: FreelanceOrder,
    sample_profile: FreelancerProfile,
):
    """Verify AIPitcher falls back to template generation when API fails."""
    config = Settings(
        ai_api_key=SecretStr("invalid_key"),
        ai_api_base_url="https://mock-ai.example.com/v1",
        ai_model="test-model",
    )
    pitcher = AIPitcher(config=config)

    respx.post("https://mock-ai.example.com/v1/models/test-model:generateContent").respond(
        status_code=500,
        text="Internal Server Error",
    )

    pitch = await pitcher.generate_pitch(sample_order, sample_profile)
    assert pitch.order_id == sample_order.id
    assert pitch.subject != ""
    assert pitch.pitch_text != ""
