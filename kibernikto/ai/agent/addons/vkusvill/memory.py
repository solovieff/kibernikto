"""Pocket memory: the last cart and the products already found in this chat, kept in this process."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.mcp import CallToolFunc, ToolResult
from pydantic_ai_harness.memory import Memory

from kibernikto.ai.agent.harness.expert_memory import conversation_key, expert_memory
from kibernikto.storage.factory import get_memory_store

logger = logging.getLogger(__name__)

STATE_DIR = 'vkusvill'
MAX_STATE_CHARS = 20_000

CART_TOOL = 'vkusvill_cart_link_create'
SEARCH_TOOL = 'vkusvill_products_search'
MAX_SEEN_PRODUCTS = 25

_SEEN_PRODUCTS: dict[str, dict[int, str]] = {}
_LAST_BASKET: dict[str, str] = {}


def _as_text(result: ToolResult) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    if isinstance(result, list):
        return ''.join(_as_text(item) for item in result)
    return ''


def _payload(result: ToolResult) -> dict[str, Any]:
    try:
        parsed = json.loads(_as_text(result))
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _product_line(item: dict[str, Any]) -> tuple[int, str] | None:
    try:
        product_id = int(item['id'])
    except (KeyError, TypeError, ValueError):
        return None
    name = str(item.get('name') or f'товар {product_id}').replace('&nbsp;', ' ')
    price = (item.get('price') or {}).get('current') if isinstance(item.get('price'), dict) else None
    return product_id, f'{name} — {price} ₽' if price is not None else name


def _remember_products(key: str, items: object) -> None:
    seen = _SEEN_PRODUCTS.setdefault(key, {})
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        line = _product_line(item)
        if line is None:
            continue
        product_id, text = line
        seen.pop(product_id, None)  # Re-insert to keep the newest products at the tail.
        seen[product_id] = text
    while len(seen) > MAX_SEEN_PRODUCTS:
        seen.pop(next(iter(seen)))


def _render_basket(key: str, products: object, link: str) -> str:
    seen = _SEEN_PRODUCTS.get(key, {})
    lines: list[str] = []
    for product in products if isinstance(products, list) else []:
        if not isinstance(product, dict):
            continue
        try:
            product_id = int(product['id'])
        except (KeyError, TypeError, ValueError):
            continue
        name = seen.get(product_id, f'товар {product_id}').split(' — ')[0]
        lines.append(f'{name} × {product.get("q", 1)}')
    return '; '.join(lines) + f'. Ссылка: {link}'


def _state_path(key: str) -> str:
    return f'{key}/{STATE_DIR}/shop.json'


async def _read_state(key: str) -> dict[str, Any]:
    try:
        file = await get_memory_store().read(_state_path(key), max_chars=MAX_STATE_CHARS)
    except Exception as exc:  # noqa: BLE001 — the pocket cache must never break a shopping run
        logger.warning('Shop memo read failed for %s: %s', key, exc)
        return {}
    try:
        data = json.loads(getattr(file, 'content', '') or '')
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


async def _write_state(key: str) -> None:
    """Replace the conversation's shop state; ``expected_version`` must match the stored file."""
    store = get_memory_store()
    path = _state_path(key)
    payload = json.dumps(
        {'basket': _LAST_BASKET.get(key), 'products': _SEEN_PRODUCTS.get(key, {})}, ensure_ascii=False,
    )
    for _ in range(2):
        try:
            current = await store.read(path, max_chars=MAX_STATE_CHARS)
            version = getattr(current, 'version', None) if current is not None else None
            await store.write(path, payload, expected_version=version)
            return
        except Exception as exc:  # noqa: BLE001 — persistence is best effort, the run continues
            logger.warning('Shop memo write failed for %s: %s', key, exc)


async def _delete_state(key: str) -> None:
    store = get_memory_store()
    path = _state_path(key)
    try:
        current = await store.read(path, max_chars=MAX_STATE_CHARS)
        if current is not None:
            await store.delete(path, expected_version=getattr(current, 'version', None))
    except Exception as exc:  # noqa: BLE001
        logger.warning('Shop memo delete failed for %s: %s', key, exc)


async def forget_shop_memory(deps: object) -> None:
    """Drop the cart and the product cache for this chat, in memory and in storage."""
    key = conversation_key(deps)
    clear_basket(deps)
    if key:
        await _delete_state(key)


async def hydrate(key: str) -> None:
    """Restore the persisted cart and product cache for a conversation into the hot dicts."""
    if key in _LAST_BASKET or key in _SEEN_PRODUCTS:
        return
    data = await _read_state(key)
    if isinstance(data.get('basket'), str):
        _LAST_BASKET[key] = data['basket']
    if isinstance(data.get('products'), dict):
        _SEEN_PRODUCTS[key] = {
            int(product_id): str(text)
            for product_id, text in data['products'].items()
            if str(product_id).isdigit()
        }


SHOP_MEMORY_HEADING = 'Shop memory'
SHOP_MEMORY_GUIDANCE = (
    "У тебя есть блокнот про покупки этого человека. Сохранённые заметки приходят в блоке "
    f"«{SHOP_MEMORY_HEADING}» его последнего сообщения — он их не писал и не видит, поэтому не цитируй их. "
    "Записывай через write_memory только то, что действительно пригодится в следующий раз: "
    "какие товары человек хвалил, что просил больше не брать, постоянные вкусы "
    "(жирность, объём, бренд, «без сахара»). Не записывай случайные позиции и сам заказ целиком — "
    "для него есть отдельная память корзины. Держи заметки короткими и правь их, а не дублируй."
)


def shop_memory(name: str) -> Memory:
    """Notebook capability: the agent curates what the shopper likes and dislikes."""
    return expert_memory(name, heading=SHOP_MEMORY_HEADING, guidance=SHOP_MEMORY_GUIDANCE)


@dataclass
class ShopMemo(AbstractCapability):
    """Loads the shop's pocket memory from the shared memory backend before each run."""

    async def before_run(self, ctx: RunContext) -> None:
        key = conversation_key(ctx.deps) or (ctx.conversation_id or None)
        if key:
            await hydrate(key)


async def remember_basket(ctx: RunContext, call_tool: CallToolFunc, name: str, args: dict[str, Any]) -> ToolResult:
    """Wrap MCP calls: cache found products and the last finished cart for this conversation."""
    result = await call_tool(name, args)
    key = conversation_key(ctx.deps)
    if key is None:
        return result
    data = _payload(result).get('data') or {}
    if name == SEARCH_TOOL:
        _remember_products(key, data.get('items'))
    elif name == CART_TOOL and data.get('link'):
        _LAST_BASKET[key] = _render_basket(key, args.get('products'), str(data['link']))
        logger.info('Basket memo updated for conversation %s', key)
    else:
        return result
    await _write_state(key)
    return result


def catalog_note(deps: object) -> str:
    """Instruction tail listing products already found in this chat, or an empty string."""
    key = conversation_key(deps)
    seen = _SEEN_PRODUCTS.get(key) if key else None
    if not seen:
        return ''
    lines = '\n'.join(f'- id {product_id}: {text}' for product_id, text in seen.items())
    return (
        '\n\nТовары, уже найденные в этом чате (бери id отсюда, не ищи их заново):\n' + lines
    )


def basket_note(deps: object) -> str:
    """Instruction tail describing the last cart in this chat, or an empty string."""
    key = conversation_key(deps)
    basket = _LAST_BASKET.get(key) if key else None
    if not basket:
        return ''
    return (
        '\n\nПоследняя собранная корзина в этом чате: ' + basket +
        '\nЕсли просят что-то поменять — собери новый набор из тех же позиций с поправкой '
        'и обязательно скажи: предыдущую корзину не открывай, актуальна новая.'
    )


def clear_basket(deps: object) -> None:
    key = conversation_key(deps)
    if key:
        _LAST_BASKET.pop(key, None)
        _SEEN_PRODUCTS.pop(key, None)
