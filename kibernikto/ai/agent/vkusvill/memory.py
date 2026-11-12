"""Pocket memory: the last cart and the products already found in this chat, kept in this process."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.mcp import CallToolFunc, ToolResult

logger = logging.getLogger(__name__)

CART_TOOL = 'vkusvill_cart_link_create'
SEARCH_TOOL = 'vkusvill_products_search'
MAX_SEEN_PRODUCTS = 25

_SEEN_PRODUCTS: dict[str, dict[int, str]] = {}
_LAST_BASKET: dict[str, str] = {}


def conversation_key(deps: object) -> str | None:
    """Chat id of this run: the parent's Telegram message survives into delegated runs."""
    message = getattr(deps, 'message', None)
    chat = getattr(message, 'chat', None)
    chat_id = getattr(chat, 'id', None)
    if chat_id is not None:
        return str(chat_id)
    user_id = getattr(deps, 'user_id', None)
    return str(user_id) if user_id is not None else None


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
