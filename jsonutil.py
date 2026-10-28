"""Defensive JSON parsing.

Wikimedia's history API truncates oversized bodies (about 32KB) and leaves a
partial trailing record. Callers should keep the complete records and move on.
"""

from __future__ import annotations

import json
from typing import TypeGuard


def is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def loads_lenient(payload: str | bytes) -> object:
    """Parse JSON, repairing a truncated tail by dropping the incomplete record."""
    text = _decode(payload)
    try:
        return json.loads(text)
    except json.JSONDecodeError as first:
        repaired = repair_truncated_json(text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            raise first from None


def loads_lenient_flagged(payload: str | bytes) -> tuple[object, bool]:
    """Return ``(value, repaired)``. ``repaired`` is true when the tail was dropped."""
    text = _decode(payload)
    try:
        return json.loads(text), False
    except json.JSONDecodeError as first:
        repaired = repair_truncated_json(text)
        try:
            return json.loads(repaired), True
        except json.JSONDecodeError:
            raise first from None


def repair_truncated_json(text: str) -> str:
    """Close a JSON document that was cut off mid-value.

    The scan remembers the end of the last complete object or array. Everything
    after that is discarded and the containers that were still open are closed.
    """
    stack: list[str] = []
    in_string = False
    escape = False
    last_index: int | None = None
    last_stack: list[str] | None = None
    index = 0
    limit = len(text)
    while index < limit:
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]":
            if not stack or stack[-1] != char:
                break
            stack.pop()
            last_index = index + 1
            last_stack = list(stack)
        index += 1
    if last_index is None or last_stack is None:
        raise json.JSONDecodeError("unrecoverable truncated JSON", text, 0)
    return text[:last_index].rstrip() + "".join(reversed(last_stack))


def object_list(value: object) -> list[dict[str, object]]:
    if is_object(value):
        return [value]
    if isinstance(value, list):
        return [item for item in value if is_object(item)]
    return []


def _decode(payload: str | bytes) -> str:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    return text.lstrip("\ufeff").strip()
