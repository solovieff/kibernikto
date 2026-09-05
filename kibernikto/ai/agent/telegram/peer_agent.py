"""A normal Kibernikto sub-agent whose inference travels through Telegram."""
from __future__ import annotations

import asyncio
import json
import math
import re
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Literal

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from pydantic_ai import AgentRunResult, ToolFailed, UserError
from pydantic_ai.messages import BinaryContent, ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from kibernikto.ai.agent.core.kibernikto_agent import KiberniktoAgent
from kibernikto.ai.agent.core.deps import KiberniktoDeps
from kibernikto.telegram.peer_protocol import PeerEnvelope, PeerProtocolError
from kibernikto.ai.agent.telegram.deps import TelegramDeps
from kibernikto.telegram.peer_hub import PeerHub, current_peer_hub


class PeerError(ToolFailed, UserError):
    """Terminal peer observation; direct callers receive an exception, never an answer.

    Harness 0.18 contains ToolFailed as a crash, but always passes UserError
    through. UserError is only a compatibility marker here: ToolFailed retains
    native failed outcomes and raw propagation without consuming retry budget.
    Unlike SkipToolExecution, this marker cannot turn a failure into a result.
    """

    def __init__(self, *, peer: int | str,
                 category: Literal['rejected', 'rate_limited', 'network', 'timeout', 'protocol', 'remote'],
                 delivery: Literal['not_sent', 'unknown'],
                 cause: Exception, retry_allowed: bool = False, retry_after: int | None = None,
                 timeout: float | None = None) -> None:
        self.peer = peer
        self.category = category
        self.delivery = delivery
        self.cause = cause
        self.retry_allowed = retry_allowed
        self.retry_after = retry_after
        self.timeout = timeout
        self.message = json.dumps({
            'kind': 'telegram_peer_failure', 'peer': peer, 'category': category,
            'delivery': delivery, 'retry_allowed': retry_allowed, 'retry_after': retry_after,
            'timeout': timeout,
            'error_type': type(cause).__name__, 'error': str(cause),
            'guidance': 'No peer answer was received. Do not automatically resend; choose another action.',
        })
        super().__init__(self.message)


@dataclass
class _Route:
    bot: Bot
    hub: PeerHub
    peer_id: int
    prompt: str
    timeout: float
    started: bool = False
    envelope: PeerEnvelope | None = None
    deps: KiberniktoDeps | None = None
    answer_text: str | None = None


_route: ContextVar[_Route] = ContextVar('kibernikto_peer_route')


class _TelegramModel(Model):
    @property
    def model_name(self) -> str:
        return 'telegram-peer'

    @property
    def system(self) -> str:
        return 'telegram'

    async def request(self, messages: list[ModelMessage], model_settings: ModelSettings | None,
                      model_request_parameters: ModelRequestParameters) -> ModelResponse:
        route = _route.get()
        route.started = True
        answer = await route.hub.request(route.bot, route.peer_id, route.prompt, timeout=route.timeout,
                                         envelope=route.envelope)
        if isinstance(answer, PeerEnvelope):
            if answer.kind == 'error':
                raise PeerError(peer=route.peer_id, category='remote', delivery='unknown',
                                cause=RuntimeError(answer.text))
            if route.deps is not None:
                route.deps.attachments.extend(answer.binaries)
            route.answer_text = answer.text
            answer = answer.text or ' '
        return ModelResponse(parts=[TextPart(answer)], model_name=self.model_name, provider_name=self.system)


class TelegramPeerAgent(KiberniktoAgent):
    """Remote peer accepted by ``SubAgent(peer)`` without a local LLM.

    Text is the default. ``multimodal=True`` uses atomic v1 byte envelopes with
    Kibernikto receivers. Select current inputs via deps.peer_inputs (an empty
    list sends none); absent selection uses only binary user_message_parts.
    URLs, history and generated parent attachments are never exported.

    Within TelegramApp handlers the sender Bot comes from TelegramDeps and the
    hub from middleware context. Outside a handler pass both explicitly. The
    peer must return a Telegram reply to the outbound message. Waits are bounded
    and process-local; restart recovery and streaming are not implemented.

    Transport failures raise PeerError with the original exception chained;
    SubAgents sees a native failed tool observation, never a peer answer or a
    retry request. A rate limit permits a later deliberate call after retry_after;
    uncertain delivery does not. No call is automatically resent. Leave the
    SubAgent timeout_seconds unset so this peer owns deadline classification.
    External cancellation and programming/configuration errors still propagate.
    """

    def __init__(self, *, peer: int | str, name: str, description: str,
                 timeout: float = 60, bot: Bot | None = None, hub: PeerHub | None = None,
                 multimodal: bool = False) -> None:
        valid_id = type(peer) is int and peer > 0
        valid_name = isinstance(peer, str) and re.fullmatch(r'@[A-Za-z][A-Za-z0-9_]{4,31}', peer)
        if not (valid_id or valid_name):
            raise ValueError('peer must be a positive private chat ID or @username')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be finite and positive')
        super().__init__(model=_TelegramModel(), name=name, description=description, history_storage=None)
        self.peer = peer
        self.timeout = timeout
        self._peer_bot = bot
        self._peer_hub = hub
        self.multimodal = multimodal

    async def run(self, user_prompt: str | None = None, *, deps: TelegramDeps | None = None,
                  **kwargs: object) -> AgentRunResult[str]:
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError('TelegramPeerAgent requires a non-empty text prompt')
        if len(user_prompt.encode('utf-16-le')) // 2 > 4096:
            raise ValueError('Telegram peer prompts must fit in one 4096-unit text message')
        if kwargs.get('output_type') not in (None, str):
            raise ValueError('TelegramPeerAgent supports text output only')
        if kwargs.get('message_history') or kwargs.get('deferred_tool_results') is not None:
            raise ValueError('Remote history/resume is not supported; include context in the prompt')
        bot = self._peer_bot or (deps.message.bot if isinstance(deps, TelegramDeps) and deps.message else None)
        hub = self._peer_hub or current_peer_hub.get(None)
        if bot is None or hub is None:
            raise RuntimeError('Use TelegramPeerAgent inside TelegramApp, or supply bot and hub explicitly')
        route: _Route | None = None
        try:
            async with hub.track_run(), asyncio.timeout(self.timeout):
                peer_id = self.peer if isinstance(self.peer, int) else (await bot.get_chat(self.peer)).id
                local_deps = deps
                envelope = None
                if self.multimodal:
                    inputs = [] if not isinstance(deps, KiberniktoDeps) else (
                        deps.peer_inputs if deps.peer_inputs is not None else
                        [p for p in deps.user_message_parts if isinstance(p, BinaryContent)])
                    envelope = PeerEnvelope.create('request', user_prompt, list(inputs))
                    local_deps = replace(deps, attachments=[]) if isinstance(deps, KiberniktoDeps) else KiberniktoDeps()
                route = _Route(bot, hub, peer_id, user_prompt, self.timeout, envelope=envelope, deps=local_deps)
                token = _route.set(route)
                try:
                    # SubAgents can forward its own model/tools; never execute them locally.
                    kwargs['model'] = self.model
                    kwargs['toolsets'] = None
                    kwargs['capabilities'] = None
                    kwargs['model_settings'] = None
                    result = await super().run(user_prompt, deps=local_deps, **kwargs)
                    if route.answer_text == '':
                        result.output = ''
                        for part in result.response.parts:
                            if isinstance(part, TextPart):
                                part.content = ''
                    if self.multimodal and isinstance(deps, KiberniktoDeps):
                        deps.attachments.extend(local_deps.attachments)
                    return result
                finally:
                    _route.reset(token)
        except PeerProtocolError as exc:
            raise PeerError(peer=self.peer, category='protocol', delivery='unknown', cause=exc) from exc
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            raise PeerError(peer=self.peer, category='rejected', delivery='not_sent', cause=exc) from exc
        except TelegramRetryAfter as exc:
            raise PeerError(peer=self.peer, category='rate_limited', delivery='not_sent', cause=exc,
                            retry_allowed=True, retry_after=exc.retry_after) from exc
        except TelegramNetworkError as exc:
            delivery = 'unknown' if route is not None and route.started else 'not_sent'
            raise PeerError(peer=self.peer, category='network', delivery=delivery, cause=exc) from exc
        except TimeoutError as exc:
            delivery = 'unknown' if route is not None and route.started else 'not_sent'
            raise PeerError(peer=self.peer, category='timeout', delivery=delivery, cause=exc,
                            timeout=self.timeout) from exc
