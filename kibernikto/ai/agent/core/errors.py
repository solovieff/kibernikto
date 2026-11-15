"""Map provider HTTP errors to a category and a short user-facing message.

Edit ``RULES`` to change how a failure is explained to users. The first matching rule wins,
so put more specific rules (by body text) before generic ones (by status code).
"""

from dataclasses import dataclass
from typing import Callable

from pydantic_ai import ModelHTTPError


class InsufficientCreditsError(Exception):
    """A billable run was refused because its chat has no credits left."""

    def __init__(self) -> None:
        super().__init__('Credits ran out. Top up: /pay. Check balance: /balance.')


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
         ModelErrorInfo('no_image_support', 'This model cannot work with images. Try text or pick another model.')),
    Rule(_status(429),
         ModelErrorInfo('rate_limited', 'The model is overloaded right now, try again in a minute.')),
    Rule(_status(401, 403),
         ModelErrorInfo('access_denied', 'The model denied access. Tell the administrator.')),
    Rule(_status(404),
         ModelErrorInfo('model_not_found', 'The selected model is unavailable. Tell the administrator.')),
    Rule(_status(400, 413, 422),
         ModelErrorInfo('bad_request', 'The model rejected the request (too large or unsuitable). Try something shorter.')),
    Rule(_status(500, 502, 503, 504),
         ModelErrorInfo('provider_unavailable', 'The model is temporarily unavailable, try again later.')),
)

FALLBACK = ModelErrorInfo('unknown', 'Could not get an answer from the model. Try again.')


def map_model_error(error: ModelHTTPError) -> ModelErrorInfo:
    """Return the category and user message for ``error``; raw provider body is never returned."""
    body = str(error.body or '')
    for rule in RULES:
        if rule.matches(error, body):
            return rule.info
    return FALLBACK
