# 🛡 Gig Sentinel

[![Python 3.14](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![aiogram 3.x](https://img.shields.io/badge/aiogram-3.x-2CA5E0.svg)](https://docs.aiogram.dev/)
[![aiosqlite](https://img.shields.io/badge/aiosqlite-async-green.svg)](https://github.com/omnilib/aiosqlite)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Tested with pytest](https://img.shields.io/badge/tested_with-pytest-0A9EDC.svg)](https://docs.pytest.org/)

**Gig Sentinel** — это фундамент коммерческого асинхронного сервиса для фрилансеров на **Python 3.14**. Сервис непрерывно мониторит новые заказы на бирже Хабр Фриланс, фильтрует их по ключевым и минус-словам, гарантирует строгую дедупликацию и генерирует персонализированные коммерческие отклики в 1 клик с помощью AI (prompt-инжиниринг).

---

## 🚀 Ключевые возможности

1. **Чистая асинхронность (`async/await`) и строгая типизация**:
   - Построено на современном стеке: `aiogram 3.x`, `aiosqlite`, `pydantic 2.x`, `pydantic-settings`, `httpx`.
   - Полная поддержка Python 3.14, строгие type hints, Pydantic-валидация и изоляция секретов.

2. **Гарантированная дедупликация заказов**:
   - Заказ **никогда не отправляется пользователю повторно**.
   - Таблица `seen_orders` с составным первичным ключом `(order_id, user_id)` и индексом обеспечивает мгновенную проверку и защиту от дублей.

3. **Гибкая система фильтрации**:
   - Положительные ключевые слова (поиск в названии, описании и тегах).
   - Минус-слова (стоп-слова) для отсечения нерелевантных заказов (например, `!wordpress`, `!битрикс`).
   - Поддержка быстрого управления через команды (`/filter add ...`, `/filter del ...`) и инлайн-меню.

4. **AI Pitch Generator (Prompt Engineering)**:
   - Анализирует полное ТЗ заказа и сопоставляет его с профилем фрилансера (опыт, навыки, ставка, портфолио).
   - Генерирует продающую структуру: хук без шаблонной воды, план реализации, релевантный стек, сроки, оценка и призыв к действию (CTA).
   - Поддерживает работу с Google Gemini API / LLM-провайдерами, а также включает встроенный детерминированный движок шаблонов при отсутствии API-ключа.

---

## 📁 Структура проекта

```text
gig-sentinel/
├── src/
│   ├── __init__.py
│   ├── config.py           # Настройки pydantic-settings, безопасные SecretStr, .env
│   ├── models.py           # Pydantic-модели (FreelanceOrder, FreelancerProfile, PitchResponse)
│   ├── database.py         # Асинхронная БД aiosqlite (users, user_keywords, seen_orders, cached_orders)
│   ├── parser.py           # Асинхронный RSS-парсер Хабр Фриланс через httpx + фильтрация
│   ├── ai_pitcher.py       # Генератор коммерческих откликов на базе prompt-инжиниринга
│   └── bot.py              # Telegram-бот aiogram 3, инлайн-кнопки и фоновый sentinel worker
├── tests/
│   ├── __init__.py
│   ├── test_database.py    # Тесты БД, CRUD профилей, ключевых слов и дедупликации
│   ├── test_parser.py      # Тесты парсинга RSS, бюджетов, HTML и фильтрации с respx моками
│   ├── test_ai_pitcher.py  # Тесты prompt-инжиниринга, mock LLM API и fallback-генератора
│   └── test_bot.py         # Тесты клавиатур и цикла фонового мониторинга с дедупликацией
├── data/                   # Локальное хранилище SQLite (создается автоматически)
├── .env.example            # Пример переменных окружения
├── .gitignore              # Исключения git
├── pyproject.toml          # Зависимости, конфигурация ruff и pytest
└── README.md               # Документация сервиса
```

---

## 🛠 Быстрый старт

### 1. Клонирование и создание виртуального окружения (Python 3.14)

```bash
git clone https://github.com/your-username/gig-sentinel.git
cd gig-sentinel

# Создание виртуального окружения Python 3.14
python3.14 -m venv .venv
source .venv/bin/activate
```

### 2. Установка зависимостей

```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

Или прямая установка:
```bash
pip install aiogram aiosqlite pydantic pydantic-settings httpx ruff pytest pytest-asyncio respx
```

### 3. Настройка переменных окружения

Скопируйте файл конфигурации:
```bash
cp .env.example .env
```

Отредактируйте `.env`:
```ini
# [Обязательно] Токен вашего бота от @BotFather
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# [Опционально] API-ключ Gemini / LLM для генерации откликов
# При отсутствии ключа бот автоматически задействует встроенный умный генератор
AI_API_KEY=AIzaSy...

# [Опционально] Модель и параметры мониторинга
AI_MODEL=gemini-2.5-flash
POLL_INTERVAL_SECONDS=120
DB_PATH=data/gig_sentinel.db
```

---

## 🧪 Запуск тестов и линтера

Проект покрыт unit-тестами с полной изоляцией и мокированием сети (`respx`):

```bash
# Запуск полного набора тестов
pytest -v

# Проверка стиля и качества кода через Ruff
ruff check .
ruff format --check .

# Автоматическое форматирование
ruff format .
```

---

## 🤖 Запуск Telegram-бота и Sentinel Worker

```bash
python -m src.bot
```

При запуске бот:
1. Инициализирует базу данных SQLite в режиме WAL (`journal_mode = WAL`) для высокой конкурентности.
2. Поднимает асинхронный диспетчер `aiogram 3`.
3. Запускает фоновую задачу `sentinel_worker`, которая с заданным интервалом:
   - Получает RSS-ленту заказов;
   - Кэширует заказы в БД;
   - Находит совпадения по фильтрам активных пользователей;
   - Проверяет отсутствие записи в `seen_orders`;
   - Отправляет сообщение в Telegram с инлайн-кнопками;
   - Фиксирует отправку в `seen_orders` для предотвращения дубликатов.

---

## 💡 Команды и взаимодействие с ботом

- `/start` — регистрация фрилансера, главное меню и статус работы бота.
- `/profile` — просмотр карточки фрилансера (специализация, стек, опыт, ставка, портфолио, статус вкл/выкл).
- `/filter` — просмотр и управление ключевыми и стоп-словами:
  - `/filter add python` — добавить отслеживание заказов по Python;
  - `/filter add !wordpress` — добавить исключение по стоп-слову;
  - `/filter del python` — удалить ключевое слово.
- `/help` — краткое руководство пользователя.

### Инлайн-кнопки под каждым заказом:
- `[ ✍️ Сгенерировать отклик (AI) ]` — запускает `AIPitcher`, формирует готовый продающий текст отклика с хуком, планом, оценкой и CTA.
- `[ 🔗 Открыть на Хабре ]` — прямая ссылка на страницу задачи.
- `[ ❌ Скрыть ]` — скрывает карточку заказа из чата.

---

## ⚖️ Лицензия

MIT License. Свободно для коммерческого использования и расширения.
