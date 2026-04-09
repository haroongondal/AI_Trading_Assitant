"""
Strip Ollama / Llama-style tool markup from assistant text so it is never shown to users.
"""
import logging
import re

logger = logging.getLogger(__name__)

_TOOL_NAMES = frozenset(
    {
        "get_portfolio",
        "add_position",
        "delete_position",
        "update_position",
        "set_portfolio_goal",
        "query_rag",
        "search_web",
        "remember",
        "recall",
    }
)


def _strip_balanced_json_object(s: str, start: int) -> int:
    """If s[start] == '{', return index after closing '}' for balanced braces (string-aware)."""
    if start >= len(s) or s[start] != "{":
        return start
    depth = 0
    i = start
    in_str = False
    esc = False
    while i < len(s):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return len(s)


def strip_ollama_tool_blocks(text: str) -> str:
    """
    Remove <|...|> segments and following JSON tool-call object if present.
    """
    if not text:
        return text
    out: list[str] = []
    i = 0
    while i < len(text):
        idx = text.find("<|", i)
        if idx == -1:
            out.append(text[i:])
            break
        out.append(text[i:idx])
        end_tag = text.find("|>", idx)
        if end_tag == -1:
            break
        j = end_tag + 2
        while j < len(text) and text[j] in " \t\r\n":
            j += 1
        if j < len(text) and text[j] == "{":
            j = _strip_balanced_json_object(text, j)
        i = j
    return "".join(out)


def strip_known_tool_json_blobs(text: str) -> str:
    """Remove embedded JSON objects that look like tool invocations (with or without python_tag)."""
    out = text
    iterations = 0
    while iterations < 100:
        iterations += 1
        changed = False
        for name in _TOOL_NAMES:
            for needle in (f'"name": "{name}"', f'"name":"{name}"'):
                i = out.find(needle)
                if i < 0:
                    continue
                start = out.rfind("{", 0, i)
                if start < 0:
                    continue
                end = _strip_balanced_json_object(out, start)
                if end > start:
                    out = out[:start] + out[end:]
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    return out


def strip_generic_tool_json_blobs(text: str) -> str:
    """
    Remove generic JSON objects that look like tool invocations, even if tool names
    are new/unknown or the object uses parameters/arguments instead of args.
    """
    out = text
    iterations = 0
    while iterations < 100:
        iterations += 1
        changed = False
        for needle in ('"name":', '"name" :'):
            i = out.find(needle)
            if i < 0:
                continue
            start = out.rfind("{", 0, i)
            if start < 0:
                continue
            end = _strip_balanced_json_object(out, start)
            candidate = out[start:end]
            # Keep scope narrow: only strip objects that resemble tool calls.
            if (
                '"name"' in candidate
                and (
                    '"args"' in candidate
                    or '"parameters"' in candidate
                    or '"arguments"' in candidate
                )
            ):
                out = out[:start] + out[end:]
                changed = True
                break
        if not changed:
            break
    return out


def sanitize_assistant_visible_text(text: str, *, trim: bool = True) -> str:
    """Full pipeline for user-visible assistant content."""
    s = strip_ollama_tool_blocks(text)
    s = strip_known_tool_json_blobs(s)
    s = strip_generic_tool_json_blobs(s)
    s = re.sub(r"<\|[^>]+\|>", "", s)
    # Gracefully degrade LaTeX-style fragments for frontends without math rendering.
    s = re.sub(r"\\\[(.*?)\\\]", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\\\((.*?)\\\)", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\\text\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\$\$(.*?)\$\$", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\$(.*?)\$", r"\1", s, flags=re.DOTALL)
    return s.strip() if trim else s


def stream_safe_text_delta(buffer: str, last_emitted_safe: str) -> tuple[str, str]:
    """
    Incremental streaming: new user-visible suffix since last emit (prefix-stable under sanitize).
    Returns (delta_to_yield, new_last_emitted_safe).
    """
    # Preserve boundary whitespace during incremental streaming so words do not collapse.
    current = sanitize_assistant_visible_text(buffer, trim=False)
    if not current:
        return "", last_emitted_safe
    if last_emitted_safe and not current.startswith(last_emitted_safe):
        logger.warning(
            "stream_safe_text_delta: non-prefix visible text (buffer_len=%s); resyncing",
            len(buffer),
        )
        return current, current
    return current[len(last_emitted_safe) :], current


def is_substantive_visible_text(text: str) -> bool:
    """True if there is user-meaningful prose left after sanitization."""
    s = sanitize_assistant_visible_text(text)
    return len(s) >= 3
