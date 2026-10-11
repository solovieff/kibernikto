"""Map provider HTTP errors to a category and a short user-facing message.

Edit ``RULES`` to change how a failure is explained to users. The first matching rule wins,
so put more specific rules (by body text) before generic ones (by status code).
"""

from dataclasses import dataclass
from typing import Callable

from pydantic_ai import ModelHTTPError


@dataclass(frozen=True)
class ModelErrorInfo:
    """Category of a model failure plus the message shown to the chat user."""

    category: str
    user_message: str


Matcher = Callable[[ModelHTTPError, str], bool]


@dataclass(frozen=True)
class Rule:
    """One mapping rule: ``matches(error, body_text)`` selects it, ``info`` describes it."""

    matches: Matcher
    info: ModelErrorInfo


def _status(*codes: int) -> Matcher:
    return lambda error, _body: error.status_code in codes


def _status_and_body(code: int, fragment: str) -> Matcher:
    return lambda error, body: error.status_code == code and fragment in body


RULES: tuple[Rule, ...] = (
    Rule(_status_and_body(404, 'Filter by Image Support'),
         ModelErrorInfo('no_image_support', 'Эта модель не умеет работать с картинками. Попробуй текст или выбери другую модель.')),
    Rule(_status(429),
         ModelErrorInfo('rate_limited', 'Модель сейчас перегружена, попробуй через минуту.')),
    Rule(_status(401, 403),
         ModelErrorInfo('access_denied', 'Модель отказала в доступе. Сообщи администратору.')),
    Rule(_status(404),
         ModelErrorInfo('model_not_found', 'Выбранная модель недоступна. Сообщи администратору.')),
    Rule(_status(400, 413, 422),
         ModelErrorInfo('bad_request', 'Запрос не принят моделью (слишком большой или неподходящий). Попробуй короче.')),
    Rule(_status(500, 502, 503, 504),
         ModelErrorInfo('provider_unavailable', 'Модель временно недоступна, попробуй позже.')),
)

FALLBACK = ModelErrorInfo('unknown', 'Не получилось получить ответ от модели. Попробуй ещё раз.')


def map_model_error(error: ModelHTTPError) -> ModelErrorInfo:
    """Return the category and user message for ``error``; raw provider body is never returned."""
    body = str(error.body or '')
    for rule in RULES:
        if rule.matches(error, body):
            return rule.info
    return FALLBACK
