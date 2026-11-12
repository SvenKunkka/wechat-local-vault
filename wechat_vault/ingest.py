"""Explicit offline import adapters. No client discovery or live acquisition."""
from __future__ import annotations
import csv
import hashlib
import json
import re
from pathlib import Path
from .errors import VaultError
from .files import input_stream, sqlite_input, locate, detached, signature
from .model import record
from .text import decode

LINE_LIMIT = 2 * 1024**2
RECORD_LIMIT = 200_000


def json_lines(path, notes):
    with input_stream(path) as stream:
        for index in range(RECORD_LIMIT + 1):
            line = stream.readline(LINE_LIMIT + 1)
            if not line:
                return
            if index == RECORD_LIMIT or len(line.encode()) > LINE_LIMIT:
                raise VaultError("The input exceeds the record or line size limit.")
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except (ValueError, RecursionError):
                raise VaultError("Invalid JSON record at line " + str(index + 1)) from None
            yield record(item)


def csv_rows(path, notes):
    csv.field_size_limit(LINE_LIMIT)
    with input_stream(path) as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or "text" not in reader.fieldnames:
            raise VaultError("CSV requires a text column and canonical field names.")
        for index, row in enumerate(reader):
            if index >= RECORD_LIMIT or None in row:
                raise VaultError("CSV exceeds the record limit or has malformed columns.")
            yield record(row)


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def tables(connection):
    return {row["name"] for row in connection.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND upper(sql) NOT LIKE 'CREATE VIRTUAL TABLE%'")}


def columns(connection, table):
    return {row["name"] for row in connection.execute("PRAGMA table_info(" + quote(table) + ")")}


def canonical_sqlite(path, notes):
    with sqlite_input(path) as connection:
        if "messages" not in tables(connection):
            raise VaultError("Canonical SQLite requires a messages table.")
        if not {"conversation", "timestamp", "text"} <= columns(connection, "messages"):
            raise VaultError("The messages table lacks required canonical fields.")
        for index, row in enumerate(connection.execute("SELECT * FROM messages")):
            if index >= RECORD_LIMIT:
                raise VaultError("Input record limit exceeded.")
            yield record(dict(row))


def pick(row, *keys, default=""):
    for key in keys:
        if key in row.keys() and row[key] not in (None, ""):
            return row[key]
    return default


def wechat_snapshot(directory, notes, *, self_id=""):
    root = locate(directory)
    if not root.is_dir():
        raise VaultError("A detached plaintext snapshot directory is required.")
    contact = root / "contact/contact.db"
    message_dir = root / "message"
    sources = sorted(message_dir.glob("message_[0-9]*.db")) if message_dir.is_dir() else []
    if not contact.is_file() or not sources:
        raise VaultError("The snapshot requires contact/contact.db and message/message_N.db files.")
    optional = {"favorite": root / "favorite/favorite.db", "moment": root / "sns/sns.db"}
    all_paths = [contact, *sources, *(p for p in optional.values() if p.is_file())]
    initial = {str(p): signature(detached(p)) for p in all_paths}
    names = {}
    hashes = {}
    count = 0
    with sqlite_input(contact) as connection:
        if "contact" not in tables(connection) or not ({"username", "userName"} & columns(connection, "contact")):
            raise VaultError("Unsupported contact schema.")
        for row in connection.execute("SELECT * FROM contact"):
            identity = decode(pick(row, "username", "userName"))
            if not identity:
                continue
            name = decode(pick(row, "remark", "nick_name", "alias", default=identity))
            names[identity] = name
            hashes[hashlib.md5(identity.encode()).hexdigest()] = identity
            count += 1
            if count > RECORD_LIMIT:
                raise VaultError("Snapshot record limit exceeded.")
            yield record({"category": "contact", "id": identity, "name": name, "text": name if name != identity else "[unnamed contact]"})
    for path in sources:
        with sqlite_input(path) as connection:
            known_tables = tables(connection)
            senders = {}
            if "Name2Id" in known_tables:
                if "user_name" in columns(connection, "Name2Id"):
                    for row in connection.execute("SELECT rowid AS internal_id, user_name FROM Name2Id"):
                        identity = decode(row["user_name"])
                        senders[row["internal_id"]] = identity
                        hashes[hashlib.md5(identity.encode()).hexdigest()] = identity
            matched = sorted(t for t in known_tables if re.fullmatch(r"Msg_[0-9a-f]{32}", t))
            if not matched:
                notes.append(path.name + ": no recognized message table")
            for table in matched:
                available = columns(connection, table)
                if not {"create_time", "message_content"} <= available:
                    raise VaultError("A message table uses an unsupported schema.")
                conversation = hashes.get(table[4:], "unresolved:" + table[4:])
                if conversation.startswith("unresolved:"):
                    notes.append("A conversation could not be resolved from contact/Name2Id metadata.")
                for row in connection.execute("SELECT rowid AS archive_rowid, * FROM " + quote(table)):
                    count += 1
                    if count > RECORD_LIMIT:
                        raise VaultError("Snapshot record limit exceeded.")
                    sender = senders.get(pick(row, "real_sender_id", default=None), "")
                    explicit = pick(row, "is_send", "isSend", default=None)
                    direction = ({"0": "in", "1": "out"}.get(str(explicit), "unknown")) if explicit is not None else (
                        ("out" if sender == self_id else "in") if sender and self_id else "unknown")
                    external_id = pick(row, "server_id", "mes_svr_id", default="")
                    if str(external_id) in ("", "0"):
                        external_id = path.name + "/" + table + "/" + str(pick(row, "local_id", "archive_rowid"))
                    body = pick(row, "message_content", default="")
                    yield record({"id": str(external_id), "conversation": conversation,
                                  "name": names.get(conversation, conversation), "sender": sender,
                                  "timestamp": row["create_time"], "kind": str(pick(row, "local_type", default="unknown")),
                                  "direction": direction, "text": body})
    for category, path in optional.items():
        if not path.is_file():
            notes.append(category + ": database not supplied")
            continue
        with sqlite_input(path) as connection:
            table = "fav_db_item" if category == "favorite" else "SnsTimeLine"
            if table not in tables(connection) or "content" not in columns(connection, table):
                notes.append(category + ": unsupported table layout")
                continue
            for row in connection.execute("SELECT rowid AS archive_rowid, * FROM " + quote(table)):
                count += 1
                if count > RECORD_LIMIT:
                    raise VaultError("Snapshot record limit exceeded.")
                yield record({"category": category,
                              "id": str(pick(row, "tid", "local_id", "archive_rowid")),
                              "sender": decode(pick(row, "user_name", "fromusr")),
                              "timestamp": pick(row, "create_time", "update_time", default=0),
                              "kind": str(pick(row, "type", default=category)),
                              "text": pick(row, "content", default="")})
    current_paths = [contact, *sorted(message_dir.glob("message_[0-9]*.db")),
                     *(p for p in optional.values() if p.is_file())]
    if {str(p) for p in current_paths} != set(initial):
        raise VaultError("Snapshot file set changed; the entire import was cancelled.")
    for path in all_paths:
        detached(path)
        if initial[str(path)] != signature(path):
            raise VaultError("Snapshot files changed; the entire import was cancelled.")


def records(path, format_name, notes, *, self_id=""):
    if format_name == "jsonl":
        yield from json_lines(path, notes)
    elif format_name == "csv":
        yield from csv_rows(path, notes)
    elif format_name == "sqlite":
        yield from canonical_sqlite(path, notes)
    elif format_name == "wechat4":
        yield from wechat_snapshot(path, notes, self_id=self_id)
    else:
        raise VaultError("Unsupported input format.")
