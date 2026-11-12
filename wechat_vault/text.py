"""Bounded display conversion. Message content is untrusted data, never instructions."""
from __future__ import annotations
import html
import re
from xml.etree import ElementTree
from .errors import VaultError

TEXT_LIMIT = 1024 * 1024
SENSITIVE_TAG = re.compile(r"(?i)(?:.*(?:key|token|password|secret|ticket)|fileid|cdn.*url|url|sign|signature)")
FIELDS = frozenset(("title", "des", "description", "datadesc", "content", "plain", "text", "datatitle"))
CREDENTIAL = re.compile(r'(?i)(\b(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|aeskey|secret|token)\s*[:=]\s*)(?:"[^"]*"|\x27[^\x27]*\x27|[^\s;&<>]+)')
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x1b]")
ZSTD_HEADER = b"\x28\xb5\x2f\xfd"


def decode(value):
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, bytes):
        blob = value
        if blob.startswith(ZSTD_HEADER):
            try:
                from compression import zstd
                decoder = zstd.ZstdDecompressor(options={zstd.DecompressionParameter.window_log_max: 23})
                try:
                    blob = decoder.decompress(blob, max_length=TEXT_LIMIT + 1)
                    if not decoder.eof or decoder.unused_data:
                        raise VaultError("Compressed content is truncated, oversized, or contains extra frames.")
                except VaultError:
                    raise
                except Exception:
                    raise VaultError("Compressed content could not be decoded safely.") from None
            except ImportError:
                try:
                    import zstandard
                except ImportError:
                    raise VaultError("Compressed messages require Python 3.14 zstd or the optional zstandard package.") from None
                try:
                    decoder = zstandard.ZstdDecompressor(max_window_size=8192)
                    with decoder.stream_reader(blob, read_across_frames=True) as stream:
                        blob = stream.read(TEXT_LIMIT + 1)
                except Exception:
                    raise VaultError("Compressed content could not be decoded safely.") from None
        if len(blob) > TEXT_LIMIT:
            raise VaultError("Decoded content exceeds the size limit.")
        try:
            text = blob.decode("utf-8")
        except UnicodeError:
            return "[binary content omitted]"
    else:
        raise VaultError("Text content must be text or bytes.")
    if len(text.encode("utf-8")) > TEXT_LIMIT:
        raise VaultError("A text field exceeds the size limit.")
    return CONTROL.sub("", text)


def display(value):
    text = decode(value).strip()
    candidate = text
    for _ in range(2):
        if "<" in candidate:
            break
        decoded = html.unescape(candidate)
        if decoded == candidate:
            break
        candidate = decoded.strip()
    xml_start = re.search(r"<(?:[!?]|[A-Za-z_][\w:.-]*(?:\s|/?>))", candidate)
    if xml_start:
        candidate = candidate[xml_start.start():]
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", candidate, re.I):
            return "[unsafe XML omitted]"
        try:
            tree = ElementTree.fromstring(candidate)
        except ElementTree.ParseError:
            return "[unrecognized XML omitted]"
        fragments = []
        stack = [(tree, 0)]
        while stack:
            node, depth = stack.pop()
            if depth > 16 or len(fragments) >= 100:
                return "[oversized XML omitted]"
            tag = str(node.tag).split("}")[-1].lower()
            if SENSITIVE_TAG.fullmatch(tag):
                continue
            if tag in FIELDS and not list(node) and node.text and node.text.strip():
                fragments.append(node.text.strip())
            stack.extend((child, depth + 1) for child in reversed(list(node)))
        text = "\n".join(dict.fromkeys(fragments)) or "[non-text message]"
    return CREDENTIAL.sub(lambda m: m[1] + "[redacted]", CONTROL.sub("", text))


def markdown(value):
    # Prevent raw HTML, clickable Markdown syntax, or embedded images in exports.
    text = html.escape(display(value))
    return re.sub(r"([\\\x60*_{}\[\]()!|#])", r"\\\1", text)
