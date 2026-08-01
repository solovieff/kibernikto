import html
import json
import typing
import re

from aiogram.client.session import aiohttp


def split_text(text: str, length: int = 4096) -> typing.List[str]:
    """
    Split long text

    :param text:
    :param length:
    :return: list of parts
    :rtype: :obj:`typing.List[str]`
    """
    return [text[i:i + length] for i in range(0, len(text), length)]


def remove_text_in_brackets_and_parentheses(text):
    return re.sub(r"[\(\[].*?[\)\]]", "", text)


def split_text_by_sentences(text, max_length):
    # Split the text into sentences by looking for periods followed by spaces, assuming this as a basic criteria for end of a sentence.
    sentences = text.split('. ')
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        # Adding 2 accounts for the period and space we split on, except for the last sentence which might not need it
        if len(current_chunk) + len(sentence) + 2 <= max_length:
            current_chunk += sentence + ". "
        else:
            # If the current chunk + the next sentence exceeds max length, store the current chunk and start a new one.
            chunks.append(current_chunk.strip())
            current_chunk = sentence + ". "

    # Add the last chunk if it's not empty, trimming the extra space and period added at the end
    if current_chunk:
        current_chunk = current_chunk.strip()
        if current_chunk.endswith('.'):
            current_chunk = current_chunk[:-1]

        chunks.append(current_chunk)

    return chunks


def split_text_into_chunks_by_sentences(text, sentences_per_chunk=2):
    # Split the text into sentences by looking for periods followed by spaces, assuming this as a basic criteria for end of a sentence.
    sentences = text.split('. ')
    chunks = []
    current_chunk = []
    sentences_count = 0

    for sentence in sentences:
        # Add the sentence to the current chunk
        current_chunk.append(sentence)
        sentences_count += 1
        # Check if the current chunk has the required number of sentences
        if sentences_count == sentences_per_chunk:
            # Join the sentences to form a chunk and add it to the chunks list
            chunks.append('. '.join(current_chunk))
            current_chunk = []
            sentences_count = 0

    # Check for any remaining sentences that didn't form a complete chunk
    if current_chunk:
        chunks.append('. '.join(current_chunk))

    return chunks


async def get_website_html(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text(encoding=response.charset)
    return html


async def get_website_as_text(url: str):
    to_reader_url = "https://toolsyep.com/en/webpage-to-plain-text/"
    async with aiohttp.ClientSession() as session:
        async with session.get(to_reader_url, params={
            "u": url
        }) as response:
            html = await response.text(encoding=response.charset)
    return html


def parse_json_garbage(s, start="{"):
    s = s[next(idx for idx, c in enumerate(s) if c in start):]
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        return json.loads(s[:e.pos])


def clear_text_format(text: str) -> str:
    """
    Clear the given text from multiple consecutive spaces, dots, and double asterisks.

    :param text: The text to be cleared.
    :type text: str
    :return: The cleared text.
    :rtype: str
    """
    format_cleared_text = text.replace("  ", " ")
    format_cleared_text = format_cleared_text.replace("....", "")
    format_cleared_text = format_cleared_text.replace("**", "")
    format_cleared_text = format_cleared_text.replace("*", "")

    return format_cleared_text


def prepare_for_MARKDOWN_V2(text: str) -> str:
    format_cleared_text = text.replace("**", "*")
    return format_cleared_text


def prepare_for_MARKDOWN(text: str) -> str:
    format_cleared_text = text.replace("**", "*")
    # No blind underscore escaping: it doubles already-escaped \_ from the model
    # and turns @swarm_host_bot into a visible @swarm\_host\_bot.
    return format_cleared_text


def markdown_to_html(text: str) -> str:
    """Convert a CommonMark subset (typical LLM output) to Telegram HTML.

    Handles fenced code blocks, headings (``#``..``######``), blockquotes,
    inline code, ``**bold**``, ``*italic*`` / ``_italic_`` and ``[text](url)``
    links. Everything else is HTML-escaped, so ``@swarm_host_bot`` stays safe.
    """
    placeholders: dict[str, str] = {}

    def _fence(match):
        lang = match.group(1)
        code = html.escape(match.group(2).strip("\n"), quote=False)
        block = f'<pre><code class="language-{lang}">{code}</code></pre>' if lang else f"<pre><code>{code}</code></pre>"
        key = f"\u0000CODE{len(placeholders)}\u0000"
        placeholders[key] = block
        return key

    # Fenced code blocks first -> placeholders so inline rules skip them.
    text = re.sub(r"```([\w+-]*)\n?(.*?)```", _fence, text, flags=re.DOTALL)

    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        line = line.rstrip()
        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            out.append(f"<blockquote>{_inline_to_html(html.escape(quote.group(1), quote=False))}</blockquote>")
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            out.append(f"<b>{_inline_to_html(html.escape(heading.group(2), quote=False))}</b>")
            continue
        out.append(_inline_to_html(html.escape(line, quote=False)))
    result = "\n".join(out)

    for key, block in placeholders.items():
        result = result.replace(key, block)
    return result


def _inline_to_html(text: str) -> str:
    """Apply inline markdown rules to an already HTML-escaped string."""
    text = re.sub(r"`([^`\n]+)`", lambda m: f"<code>{m.group(1)}</code>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link_repl, text)
    text = re.sub(r"\*\*(.+?)\*\*", _bold_repl, text)
    text = re.sub(r"(?<!\w)\*(?!\*)([^*\n]+)\*(?!\*)|(?<!\w)_([^_\n]+)_(?!\w)", _italic_repl, text)
    return text


def _link_repl(match):
    # href is already HTML-escaped by the caller; escaping again doubles &amp;.
    return f'<a href="{match.group(2)}">{_inline_to_html(match.group(1))}</a>'


def _bold_repl(match):
    return f"<b>{_inline_to_html(match.group(1))}</b>"


def _italic_repl(match):
    body = match.group(1) if match.group(1) is not None else match.group(2)
    return f"<i>{_inline_to_html(body)}</i>"


def text_to_html(text: str) -> str:
    """

    :param text:
    :return:
    """
    html_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)

    return html_text
