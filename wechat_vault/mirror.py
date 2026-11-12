"""Explicit Mac source refresh into immutable, private plaintext generations."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import sqlite3
import stat
import tempfile
from .cipher import CommonCrypto, PROFILE
from .errors import VaultError
from .files import locate, private_folder, publish, signature, sqlite_input, write_lock
from .wal import reconstruct

FORMAT = "wechat-local-vault-mirror/1"
MAX_DATABASES = 256


def private_file(path, *, maximum=512 * 1024):
    target = locate(path)
    info = target.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > maximum:
        raise VaultError("A private, owned, regular 0600 file within the size limit is required.")
    return target


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise VaultError("Duplicate keys in a private JSON mapping are not accepted.")
        value[key] = item
    return value


def read_private_json(path):
    target = private_file(path)
    with captured_input(target) as stream:
        value = json.load(stream, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise VaultError("Invalid private JSON structure.")
    return value


def relative_database(name):
    if not isinstance(name, str):
        raise VaultError("Database paths must be relative text.")
    value = PurePosixPath(name)
    if value.is_absolute() or not value.parts or any(part in (".", "..") for part in value.parts) or value.as_posix() != name or "\\" in name or value.suffix != ".db":
        raise VaultError("Database entries require canonical relative .db paths.")
    return value


def key_mapping(path, account):
    data = read_private_json(path)
    entries = data.get("databases")
    if data.get("account") != account or data.get("profile") != PROFILE or not isinstance(entries, dict) or not 1 <= len(entries) <= MAX_DATABASES:
        raise VaultError("Key mapping account, profile or database selection is invalid.")
    result = {}
    for name, value in entries.items():
        relative_database(name)
        if not isinstance(value, str) or len(value) != 64:
            raise VaultError("Each selected database requires a 64-character raw key.")
        try:
            raw = bytes.fromhex(value)
        except ValueError:
            raise VaultError("A supplied raw key is invalid.") from None
        if len(raw) != 32:
            raise VaultError("A supplied raw key is invalid.")
        result[name] = raw
    return result


def overlap(first, second):
    return first == second or first in second.parents or second in first.parents


def file_set(source, names):
    result = {}
    for name in names:
        main = locate(source / name)
        result[name] = list(signature(main))
        for suffix in ("-wal", "-shm", "-journal"):
            path = locate(str(main) + suffix)
            if suffix == "-journal" and path.exists():
                raise VaultError("Rollback journals are not supported; source was not changed.")
            result[name + suffix] = list(signature(path)) if path.exists() else None
    return result


@contextmanager
def captured_input(path):
    before = signature(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != before[:2]:
            raise VaultError("Source changed before capture.")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            yield stream
            info = os.fstat(stream.fileno())
            observed = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            if tuple(before) != observed or before != signature(path):
                raise VaultError("Source changed during capture.")
    finally:
        if fd >= 0:
            os.close(fd)


def copy_private(source, destination):
    private_folder(destination.parent)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output, captured_input(source) as input_file:
        shutil.copyfileobj(input_file, output, 1024 * 1024)
        output.flush()
        os.fsync(output.fileno())


def digest(path):
    value = hashlib.sha256()
    with captured_input(path) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def validate_plaintext(path):
    with sqlite_input(path) as connection:
        connection.execute("PRAGMA temp_store=MEMORY")
        rows = connection.execute("PRAGMA integrity_check").fetchall()
        if len(rows) != 1 or rows[0][0] != "ok":
            raise VaultError("Decrypted SQLite integrity validation failed.")


class Mirror:
    def __init__(self, directory):
        self.root = locate(directory)
        self.marker = self.root / "mirror.json"

    def state(self):
        info = self.root.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise VaultError("Mirror state requires a private owned root directory.")
        value = read_private_json(self.marker)
        generation = value.get("generation", "")
        if value.get("format") != FORMAT or value.get("profile") != PROFILE or not isinstance(generation, str) or not generation.startswith("g-") or len(generation) != 34 or any(c not in "0123456789abcdef" for c in generation[2:]):
            raise VaultError("Invalid mirror state.")
        entries = value.get("files")
        if not isinstance(entries, dict) or not 1 <= len(entries) <= MAX_DATABASES:
            raise VaultError("Invalid mirror file manifest.")
        for field in ("cache_key", "source_binding"):
            token = value.get(field)
            if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
                raise VaultError("Invalid mirror binding metadata.")
        for name, item in entries.items():
            relative_database(name)
            if not isinstance(item, dict) or not isinstance(item.get("source"), dict) or set(item["source"]) != {"", "-wal", "-shm", "-journal"}:
                raise VaultError("Invalid mirror file metadata.")
            for field in ("plaintext_sha256", "key_token"):
                token = item.get(field)
                if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
                    raise VaultError("Invalid mirror digest metadata.")
            for field in ("pages", "wal_frames", "committed_frames", "uncommitted_frames"):
                number = item.get(field)
                if not isinstance(number, int) or isinstance(number, bool) or number < 0:
                    raise VaultError("Invalid mirror counters.")
        return value

    def current(self):
        state = self.state()
        directory = locate(self.root / "generations" / state["generation"])
        info = directory.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise VaultError("Current mirror generation must be a private owned directory.")
        for name, item in state.get("files", {}).items():
            relative_database(name)
            path = private_file(directory / name, maximum=2 * 1024**3)
            if digest(path) != item["plaintext_sha256"]:
                raise VaultError("Current plaintext generation was modified.")
        return directory

    def synchronize(self, *, source, keys, account, confirmed=False, mode="incremental", allow_live=False, provider=None):
        # Authorization precedes path resolution, key reads, state reads and library loading.
        if not confirmed:
            raise VaultError("Explicit --confirm-source is required before encrypted-source access.")
        if mode not in ("full", "incremental") or not isinstance(account, str) or not account.strip() or len(account) > 200:
            raise VaultError("Invalid mode or account label.")
        source = locate(source)
        if not source.is_dir() or source in (Path("/"), Path.home()):
            raise VaultError("Select one explicit database source directory.")
        if not allow_live and ("/Containers/com.tencent.xinWeChat/" in str(source) + "/" or "/xwechat_files/" in str(source) + "/"):
            raise VaultError("Live client paths require separate --allow-live-source authorization.")
        if overlap(source, self.root):
            raise VaultError("Encrypted source and plaintext output must be separate.")
        key_path = locate(keys)
        if overlap(self.root, key_path) or overlap(source, key_path):
            raise VaultError("Keep key files separate from source and generated output.")
        binding = hashlib.sha256((str(source) + "\0" + account).encode()).hexdigest()
        previous = None
        if self.marker.exists():
            previous = self.state()
            if previous.get("account") != account or previous.get("source_binding") != binding:
                raise VaultError("Mirror account/source binding mismatch.")
        elif self.root.exists() and any(self.root.iterdir()):
            # A failed first run can leave only the empty private scaffolding it created.
            names = {item.name for item in self.root.iterdir()}
            generations = self.root / "generations"
            if not names <= {".writer.lock", "generations"} or (generations.exists() and any(locate(generations).iterdir())):
                raise VaultError("Use a new or empty dedicated mirror directory.")
        key_signature = signature(key_path)
        selected = key_mapping(key_path, account)
        native = provider if provider is not None else CommonCrypto()
        private_folder(self.root)
        with write_lock(self.root):
            # A parallel writer must not replace the state checked above.
            if (previous is None and self.marker.exists()) or (previous is not None and self.state() != previous):
                raise VaultError("Mirror state changed before the writer lock was acquired.")
            initial = file_set(source, selected)
            cache_secret = bytes.fromhex(previous["cache_key"]) if previous else secrets.token_bytes(32)
            generation = "g-" + secrets.token_hex(16)
            generations = private_folder(self.root / "generations")
            output = private_folder(generations / generation)
            files, changed, reused = {}, 0, 0
            committed = False
            try:
                with tempfile.TemporaryDirectory(prefix=".capture-", dir=self.root) as capture:
                    captured = Path(capture)
                    for name, key in sorted(selected.items()):
                        stamp = {suffix: initial[name + suffix] for suffix in ("", "-wal", "-shm", "-journal")}
                        key_token = hmac.digest(cache_secret, key, "sha256").hex()
                        old = previous.get("files", {}).get(name) if previous else None
                        target = output / name
                        private_folder(target.parent)
                        cached = locate(generations / previous["generation"] / name) if old else None
                        if mode == "incremental" and old and old["source"] == stamp and old["key_token"] == key_token:
                            try:
                                private_file(cached, maximum=2 * 1024**3)
                                if digest(cached) != old["plaintext_sha256"]:
                                    raise VaultError("Cached plaintext was modified.")
                                copy_private(cached, target)
                                if digest(target) != old["plaintext_sha256"]:
                                    raise VaultError("Cached plaintext changed between validation and copying.")
                                information = {key: old[key] for key in ("pages", "wal_frames", "committed_frames", "uncommitted_frames")}
                                reused += 1
                            except (OSError, VaultError):
                                # A damaged cache is not trusted. Rebuild from authenticated input.
                                if target.exists():
                                    target.unlink()
                                cached = None
                        else:
                            cached = None
                        if cached is None:
                            main_copy = captured / name
                            copy_private(source / name, main_copy)
                            wal_copy = None
                            if initial[name + "-wal"] is not None:
                                wal_copy = Path(str(main_copy) + "-wal")
                                copy_private(Path(str(source / name) + "-wal"), wal_copy)
                            information = reconstruct(main_copy, wal_copy, target, key, native)
                            validate_plaintext(target)
                            changed += 1
                        files[name] = {"source": stamp, "key_token": key_token, "plaintext_sha256": digest(target), **information}
                    if initial != file_set(source, selected) or signature(key_path) != key_signature:
                        raise VaultError("Source or key mapping changed; previous generation remains current.")
                    state = {"format": FORMAT, "account": account, "source_binding": binding,
                             "cache_key": cache_secret.hex(), "generation": generation, "files": files,
                             "completed_at": datetime.now(timezone.utc).isoformat(), "profile": PROFILE}
                if initial != file_set(source, selected) or signature(key_path) != key_signature:
                    raise VaultError("Source or key mapping changed before publication.")
                publish(self.marker, json.dumps(state, ensure_ascii=False, indent=2) + "\n", update=previous is not None)
                committed = True
                return {"decrypted": changed, "reused": reused, "databases": len(files), "generation": generation,
                        "completed_at": state["completed_at"], "mode": mode,
                        "uncommitted_wal_frames": sum(item["uncommitted_frames"] for item in files.values()),
                        "stage": "decryption complete; normalized archive not updated"}
            finally:
                if not committed:
                    # Only remove this run's newly allocated staging output; never prior generations/source.
                    shutil.rmtree(output)
