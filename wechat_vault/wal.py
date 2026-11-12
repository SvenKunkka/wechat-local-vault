"""Strict SQLite WAL parser. No source checkpointing and no ignored corrupt tail."""
from __future__ import annotations
import struct
from dataclasses import dataclass
from .cipher import PAGE
from .errors import VaultError

MAX_PAGES = (2 * 1024**3) // PAGE


def checksum(payload, order, state=(0, 0)):
    if len(payload) % 8:
        raise VaultError("Invalid WAL checksum input.")
    values = struct.iter_unpack(order + "II", payload)
    first, second = state
    for left, right in values:
        first = (first + left + second) & 0xffffffff
        second = (second + right + first) & 0xffffffff
    return first, second


@dataclass
class WalIndex:
    pages: dict
    database_pages: int | None
    frames: int
    committed_frames: int
    uncommitted_frames: int


def index_wal(path, decoder):
    if path is None or path.stat().st_size == 0:
        return WalIndex({}, None, 0, 0, 0)
    size = path.stat().st_size
    if size < 32 or (size - 32) % (PAGE + 24):
        raise VaultError("WAL has an incomplete header or frame.")
    with path.open("rb") as stream:
        header = stream.read(32)
        magic, version, page_size, sequence, salt1, salt2, check1, check2 = struct.unpack(">8I", header)
        if magic not in (0x377f0682, 0x377f0683) or version != 3007000 or page_size != PAGE:
            raise VaultError("Unsupported WAL header.")
        order = "<" if magic == 0x377f0682 else ">"
        running = checksum(header[:24], order)
        if running != (check1, check2):
            raise VaultError("WAL header checksum failed.")
        offsets, committed, final_size, last_commit, count = {}, {}, None, 0, 0
        while stream.tell() < size:
            frame = stream.read(24)
            number, database_size, one, two, left, right = struct.unpack(">6I", frame)
            payload_offset = stream.tell()
            page = stream.read(PAGE)
            if (one, two) != (salt1, salt2):
                raise VaultError("WAL frame salt mismatch; stale/corrupt tails are not accepted.")
            if not 1 <= number <= MAX_PAGES or database_size > MAX_PAGES:
                raise VaultError("WAL page number or commit size exceeds limits.")
            running = checksum(frame[:8] + page, order, running)
            if running != (left, right):
                raise VaultError("WAL frame checksum failed.")
            decoder.authenticate(page, number)
            offsets[number] = payload_offset
            count += 1
            if database_size:
                committed.update(offsets)
                committed = {page: offset for page, offset in committed.items() if page <= database_size}
                offsets.clear()
                final_size, last_commit = database_size, count
        return WalIndex(committed, final_size, count, last_commit, count - last_commit)


def reconstruct(main, wal, destination, key, provider):
    from .cipher import PageDecoder
    size = main.stat().st_size
    if size < PAGE or size % PAGE or size > MAX_PAGES * PAGE:
        raise VaultError("Encrypted main file has an unsupported size.")
    with main.open("rb") as source:
        decoder = PageDecoder(key, source.read(16), provider)
        index = index_wal(wal, decoder)
        base_pages = size // PAGE
        final_pages = index.database_pages or base_pages
        if any(number not in index.pages for number in range(base_pages + 1, final_pages + 1)):
            raise VaultError("Committed WAL growth has missing pages.")
        import os
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            source.seek(0)
            for number in range(1, base_pages + 1):
                plain = decoder.decode(source.read(PAGE), number)
                if number <= final_pages:
                    output.write(plain)
            if wal is not None:
                with wal.open("rb") as log:
                    for number, offset in index.pages.items():
                        if number <= final_pages:
                            log.seek(offset)
                            output.seek((number - 1) * PAGE)
                            output.write(decoder.decode(log.read(PAGE), number))
            output.truncate(final_pages * PAGE)
            output.flush()
            os.fsync(output.fileno())
    return {"pages": final_pages, "wal_frames": index.frames,
            "committed_frames": index.committed_frames, "uncommitted_frames": index.uncommitted_frames}
