"""POSIX file operations; no filesystem access occurs at import time."""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from .errors import VaultError

MAX_INPUT_BYTES = 2 * 1024**3


def locate(value) -> Path:
    path = Path(os.path.abspath(Path(value).expanduser()))
    for component in [*reversed(path.parents), path]:
        if component.is_symlink():
            raise VaultError("Symbolic links are not accepted.")
    return path


def private_folder(value) -> Path:
    target = locate(value)
    forbidden = {Path("/"), Path.home(), Path.home() / "Documents",
                 Path.home() / "Desktop", Path.home() / "Library",
                 Path.home() / "Library/Application Support"}
    if target in forbidden:
        raise VaultError("Choose a dedicated vault or export directory.")
    missing = []
    parent = target
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for item in reversed(missing):
        item.mkdir(mode=0o700)
    info = target.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise VaultError("Private directories must be owned by the current user.")
    if info.st_mode & 0o077 and any(target.iterdir()):
        raise VaultError("Use an empty or already private dedicated directory; existing shared permissions were not changed.")
    target.chmod(0o700)
    return target


def publish(destination, payload: str, *, update=False):
    target = locate(destination)
    parent = private_folder(target.parent)
    if target.exists():
        info = target.stat()
        if not update:
            raise VaultError("The output already exists; select a new filename.")
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise VaultError("Refusing an unsafe replacement target.")
    descriptor, temporary = tempfile.mkstemp(prefix=".publish-", dir=parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if update:
            os.replace(temporary, target)
        else:
            os.link(temporary, target, follow_symlinks=False)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def signature(value):
    path = locate(value)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_INPUT_BYTES:
        raise VaultError("Input must be a regular file within the size limit.")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def detached(value):
    path = locate(value)
    # This release deliberately refuses the normal live client container.
    text = path.as_posix()
    if "/Containers/com.tencent.xinWeChat/" in text or "/xwechat_files/" in text:
        raise VaultError("Select a detached export outside the live client data tree.")
    signature(path)
    for ending in ("-wal", "-shm", "-journal"):
        if os.path.lexists(str(path) + ending):
            raise VaultError("Input has active or unmerged SQLite sidecars.")
    return path


@contextmanager
def input_stream(value, *, binary=False):
    path = detached(value)
    before = signature(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != before[:2]:
            raise VaultError("Input was replaced before it could be read.")
        with os.fdopen(descriptor, "rb" if binary else "r", **({} if binary else {"encoding": "utf-8-sig", "newline": ""})) as handle:
            descriptor = -1
            yield handle
            observed = os.fstat(handle.fileno())
            after_fd = (observed.st_dev, observed.st_ino, observed.st_size,
                        observed.st_mtime_ns, observed.st_ctime_ns)
            if before != after_fd or before != signature(path):
                raise VaultError("Input changed during import; the transaction was cancelled.")
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@contextmanager
def sqlite_input(value):
    path = detached(value)
    before = signature(path)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 4 * 1024**2)
        connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 256)
        connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65536)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise VaultError("Input database failed its SQLite consistency check.")
        yield connection
        detached(path)
        if signature(path) != before:
            raise VaultError("Input database changed during import.")
    finally:
        connection.close()


@contextmanager
def write_lock(directory):
    root = private_folder(directory)
    path = locate(root / ".writer.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise VaultError("Invalid vault lock.")
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise VaultError("Another process is updating this vault.") from None
        yield
    finally:
        os.close(fd)
