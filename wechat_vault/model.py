"""The public interchange format is independent of any vendor database."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from .errors import VaultError
from .text import decode, display

CATEGORIES = ("message", "contact", "favorite", "moment")
KEYS = ("category", "id", "conversation", "name", "sender", "timestamp", "kind", "text", "direction")


def epoch(value, *, required=False):
    if value in (None, ""):
        if required:
            raise VaultError("Messages require an explicit timestamp.")
        return 0
    if isinstance(value, bool):
        raise VaultError("Boolean timestamps are invalid.")
    if isinstance(value, int) or (isinstance(value, str) and value.isdecimal()):
        number = int(value)
        if number > 100_000_000_000:
            number //= 1000
        if not 0 <= number <= 253402300799:
            raise VaultError("Timestamp is outside the supported range.")
        return number
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                raise ValueError
            result = int(moment.timestamp())
            if result < 0:
                raise ValueError
            return result
        except (ValueError, OverflowError):
            pass
    raise VaultError("Use Unix seconds/milliseconds or an ISO timestamp with timezone.")


def record(item):
    if not isinstance(item, dict):
        raise VaultError("Every record must be a JSON object.")
    category = item.get("category", "message")
    if category not in CATEGORIES:
        raise VaultError("Unknown record category.")
    result = {"category": category}
    for key in ("id", "conversation", "name", "sender", "kind"):
        value = item.get(key, "")
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise VaultError("Identifiers and labels must be scalar text.")
        result[key] = decode(str(value))
        if len(result[key]) > 2048:
            raise VaultError("An identifier or label is too long.")
    result["text"] = display(item.get("text", ""))
    result["timestamp"] = epoch(item.get("timestamp"), required=category == "message")
    result["direction"] = item.get("direction") or "unknown"
    if result["direction"] not in ("in", "out", "unknown"):
        raise VaultError("Direction must be in, out, or unknown.")
    if category == "message" and not result["conversation"]:
        raise VaultError("Messages require a conversation identifier.")
    if not result["id"]:
        body = json.dumps(result, sort_keys=True, ensure_ascii=False).encode()
        result["id"] = hashlib.sha256(body).hexdigest()
    return result


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
