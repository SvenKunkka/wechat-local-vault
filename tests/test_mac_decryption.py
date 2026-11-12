"""Synthetic authenticated pages and WAL transactions; no real client or keys."""
from __future__ import annotations
import contextlib
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import unittest
from unittest import mock
from test_archive import Harness, synthetic_database
from wechat_vault.cipher import CommonCrypto, PAGE, USABLE, PROFILE
from wechat_vault.errors import VaultError
from wechat_vault.mirror import Mirror
from wechat_vault.wal import checksum, index_wal

# Public NIST test data and deterministic fictional account keys only.
FAKE_KEY = bytes(range(32))
FAKE_SALT = bytes(range(16))
ROOM = "Msg_" + hashlib.md5(b"demo-room").hexdigest()


class IdentityTestCipher:
    """Protocol tests on Linux only; never available through the production CLI."""
    def crypt(self, key, iv, payload, *, encrypt=False):
        return payload

    def decrypt(self, key, iv, payload):
        return payload


def test_provider():
    return CommonCrypto() if sys.platform == "darwin" else IdentityTestCipher()


def reserved_database(path, statements):
    with synthetic_database(path) as connection:
        connection.execute("PRAGMA page_size=4096")
        for sql, parameters in statements:
            connection.execute(sql, parameters)
    data = bytearray(path.read_bytes())
    data[20] = 80
    for offset in range(0, len(data), PAGE):
        header = offset + (100 if offset == 0 else 0)
        if data[header] != 13 or data[header + 1:header + 3] != b"\0\0":
            raise AssertionError("Synthetic fixture requires small leaf tables.")
        count = int.from_bytes(data[header + 3:header + 5], "big")
        top = int.from_bytes(data[header + 5:header + 7], "big")
        if top < (header - offset) + 8 + 2 * count + 80:
            raise AssertionError("Fixture is too large.")
        area = bytes(data[offset + top:offset + PAGE])
        data[offset + top - 80:offset + USABLE] = area
        data[offset + USABLE:offset + PAGE] = bytes(80)
        data[header + 5:header + 7] = (top - 80).to_bytes(2, "big")
        for number in range(count):
            position = header + 8 + 2 * number
            cell = int.from_bytes(data[position:position + 2], "big")
            data[position:position + 2] = (cell - 80).to_bytes(2, "big")
    path.write_bytes(data)
    with contextlib.closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    return [bytes(data[start:start + PAGE]) for start in range(0, len(data), PAGE)]


def encrypted_page(plain, number, provider, key=FAKE_KEY, salt=FAKE_SALT):
    start = 16 if number == 1 else 0
    iv = hashlib.sha256(b"fictional-iv" + plain + struct.pack(">I", number)).digest()[:16]
    encrypted = provider.crypt(key, iv, plain[start:USABLE], encrypt=True)
    auth = hashlib.pbkdf2_hmac("sha512", key, bytes(value ^ 0x3a for value in salt), 2, 32)
    tag = hmac.digest(auth, encrypted + iv + struct.pack("<I", number), "sha512")
    return (salt if number == 1 else b"") + encrypted + iv + tag


def wal_file(frames, *, order="<"):
    magic = 0x377f0682 if order == "<" else 0x377f0683
    salt = (101, 202)
    header = struct.pack(">6I", magic, 3007000, PAGE, 0, *salt)
    running = checksum(header, order)
    body = header + struct.pack(">2I", *running)
    for number, commit, page in frames:
        prefix = struct.pack(">2I", number, commit)
        running = checksum(prefix + page, order, running)
        body += prefix + struct.pack(">4I", *salt, *running) + page
    return body


class MacDecryptionCase(Harness):
    def setUp(self):
        super().setUp()
        self.provider = test_provider()
        self.source_dir = self.root / "encrypted"
        self.source_dir.mkdir()
        self.key_file = self.root / "private-keys.json"
        self.keys = {"contact/contact.db": FAKE_KEY.hex(), "message/message_0.db": FAKE_KEY.hex()}
        self.key_file.write_text(json.dumps({"account": "demo-account", "profile": PROFILE, "databases": self.keys}))
        self.key_file.chmod(0o600)
        self.contact_pages = self.contact()
        self.message_pages = self.messages(["one"])
        for name, pages in (("contact/contact.db", self.contact_pages), ("message/message_0.db", self.message_pages)):
            path = self.source_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"".join(encrypted_page(page, i + 1, self.provider) for i, page in enumerate(pages)))
        self.mirror = Mirror(self.root / "mirror")

    def contact(self):
        path = self.root / "contact-fixture.sqlite"
        return reserved_database(path, [
            ("CREATE TABLE contact(username TEXT,remark TEXT)", ()),
            ("INSERT INTO contact VALUES (?,?)", ("demo-room", "Synthetic room")),
            ("INSERT INTO contact VALUES (?,?)", ("demo-friend", "Synthetic friend"))])

    def messages(self, texts):
        path = self.root / ("messages-" + str(len(texts)) + "-" + str(len(list(self.root.glob("messages-*.sqlite")))) + ".sqlite")
        sql = [("CREATE TABLE Name2Id(user_name TEXT)", ())]
        sql += [("INSERT INTO Name2Id VALUES (?)", (name,)) for name in ("demo-self", "demo-friend", "demo-room")]
        sql += [('CREATE TABLE "' + ROOM + '"(local_id INTEGER,server_id INTEGER,create_time INTEGER,message_content TEXT,real_sender_id INTEGER,is_send INTEGER)', ())]
        sql += [('INSERT INTO "' + ROOM + '" VALUES (?,?,?,?,?,?)', (index + 1, index + 100, 1700000000 + index, text, 2, 0)) for index, text in enumerate(texts)]
        return reserved_database(path, sql)

    def sync(self, **changes):
        options = dict(source=self.source_dir, keys=self.key_file, account="demo-account", confirmed=True, provider=self.provider)
        options.update(changes)
        return self.mirror.synchronize(**options)

    def add_wal(self, texts, *, committed=True, order="<", trailing=None):
        pages = self.messages(texts)
        frames = [(i + 1, len(pages) if committed and i == len(pages) - 1 else 0,
                   encrypted_page(page, i + 1, self.provider)) for i, page in enumerate(pages)]
        if trailing is not None:
            tail = self.messages(trailing)[-1]
            frames.append((len(pages), 0, encrypted_page(tail, len(pages), self.provider)))
        path = self.source_dir / "message/message_0.db-wal"
        path.write_bytes(wal_file(frames, order=order))
        return path

    def current_messages(self):
        path = self.mirror.current() / "message/message_0.db"
        with contextlib.closing(sqlite3.connect(path)) as connection:
            return [row[0] for row in connection.execute('SELECT message_content FROM "' + ROOM + '" ORDER BY local_id')]

    def test_full_authenticated_decryption_and_private_outputs(self):
        before = {str(path): path.read_bytes() for path in self.source_dir.rglob("*.db")}
        result = self.sync(mode="full")
        self.assertEqual((result["decrypted"], result["reused"]), (2, 0))
        self.assertEqual(self.current_messages(), ["one"])
        for path in self.mirror.current().rglob("*.db"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.source_dir.rglob("*.db")})
        self.assertNotIn(FAKE_KEY.hex(), self.mirror.marker.read_text())

    def test_unchanged_input_reuses_authenticated_plaintext(self):
        self.sync()
        self.assertEqual(self.sync()["reused"], 2)
        self.assertEqual(self.current_messages(), ["one"])

    def test_wal_only_change_reads_committed_new_message(self):
        self.sync()
        main = self.source_dir / "message/message_0.db"
        before = main.read_bytes(), main.stat().st_mtime_ns
        self.add_wal(["one", "two"])
        result = self.sync()
        self.assertEqual((result["decrypted"], result["reused"]), (1, 1))
        self.assertEqual(self.current_messages(), ["one", "two"])
        self.assertEqual(before, (main.read_bytes(), main.stat().st_mtime_ns))

    def test_uncommitted_transaction_is_excluded(self):
        self.add_wal(["one", "two"], committed=False)
        result = self.sync()
        self.assertEqual(self.current_messages(), ["one"])
        self.assertEqual(result["uncommitted_wal_frames"], 3)

    def test_committed_prefix_with_valid_uncommitted_tail(self):
        self.add_wal(["one", "two"], trailing=["one", "two", "uncommitted"])
        self.assertEqual(self.sync()["uncommitted_wal_frames"], 1)
        self.assertEqual(self.current_messages(), ["one", "two"])

    def test_both_wal_checksum_byte_orders(self):
        self.add_wal(["one", "two"], order=">")
        self.sync()
        self.assertEqual(self.current_messages(), ["one", "two"])

    def test_wrong_key_does_not_replace_current(self):
        self.sync()
        previous = self.mirror.marker.read_bytes()
        data = json.loads(self.key_file.read_text())
        data["databases"]["message/message_0.db"] = bytes(reversed(FAKE_KEY)).hex()
        self.key_file.write_text(json.dumps(data))
        with self.assertRaises(VaultError):
            self.sync()
        self.assertEqual(self.mirror.marker.read_bytes(), previous)
        self.assertEqual(self.current_messages(), ["one"])

    def test_modified_main_page_is_rejected(self):
        self.sync()
        previous = self.mirror.marker.read_bytes()
        path = self.source_dir / "message/message_0.db"
        value = bytearray(path.read_bytes()); value[PAGE + 100] ^= 1; path.write_bytes(value)
        with self.assertRaises(VaultError):
            self.sync()
        self.assertEqual(previous, self.mirror.marker.read_bytes())

    def test_wal_checksum_failure_preserves_current(self):
        self.sync()
        previous = self.mirror.marker.read_bytes()
        path = self.add_wal(["one", "two"])
        value = bytearray(path.read_bytes()); value[156] ^= 1; path.write_bytes(value)
        with self.assertRaises(VaultError):
            self.sync()
        self.assertEqual(previous, self.mirror.marker.read_bytes())

    def test_wal_authentication_failure_even_with_valid_checksum(self):
        self.sync()
        previous = self.mirror.marker.read_bytes()
        page = bytearray(encrypted_page(self.message_pages[-1], 3, self.provider)); page[100] ^= 1
        path = self.source_dir / "message/message_0.db-wal"
        path.write_bytes(wal_file([(3, 3, bytes(page))]))
        with self.assertRaises(VaultError):
            self.sync()
        self.assertEqual(previous, self.mirror.marker.read_bytes())

    def test_truncated_wal_is_not_silently_ignored(self):
        path = self.add_wal(["one", "two"])
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(VaultError):
            self.sync()

    def test_source_mutation_aborts_batch(self):
        self.sync()
        previous = self.mirror.marker.read_bytes()
        from wechat_vault import mirror
        original = mirror.reconstruct
        def changing(*args):
            result = original(*args)
            path = self.source_dir / "message/message_0.db"
            os.utime(path, None)
            return result
        with mock.patch("wechat_vault.mirror.reconstruct", side_effect=changing), self.assertRaises(VaultError):
            self.sync(mode="full")
        self.assertEqual(previous, self.mirror.marker.read_bytes())

    def test_modified_cached_plaintext_rebuilds_from_encrypted_source(self):
        self.sync()
        path = self.mirror.current() / "message/message_0.db"
        path.write_bytes(b"damaged cache")
        self.assertEqual(self.sync()["decrypted"], 1)
        self.assertEqual(self.current_messages(), ["one"])

    def test_cache_mutation_between_validation_and_copy_rebuilds(self):
        self.sync()
        cached = self.mirror.current() / "message/message_0.db"
        from wechat_vault import mirror
        original = mirror.copy_private
        changed = []
        def changing(source, destination):
            if source == cached and not changed:
                with synthetic_database(cached) as connection:
                    connection.execute('UPDATE "' + ROOM + '" SET message_content=?', ("unauthenticated edit",))
                changed.append(True)
            return original(source, destination)
        with mock.patch("wechat_vault.mirror.copy_private", side_effect=changing):
            result = self.sync()
        self.assertEqual(result["decrypted"], 1)
        self.assertEqual(result["reused"], 1)
        self.assertEqual(self.current_messages(), ["one"])

    def test_missing_cache_rebuilds(self):
        self.sync()
        path = self.mirror.current() / "message/message_0.db"
        path.unlink()
        self.assertEqual(self.sync()["decrypted"], 1)

    def test_source_account_binding_is_enforced(self):
        self.sync()
        with self.assertRaises(VaultError):
            self.sync(account="another-account")

    def test_source_confirmation_precedes_access(self):
        with mock.patch("wechat_vault.mirror.locate", side_effect=AssertionError("source accessed")), self.assertRaises(VaultError):
            self.sync(confirmed=False)

    def test_cli_confirmation_precedes_mirror_creation(self):
        from wechat_vault.cli import main
        with mock.patch("wechat_vault.mirror.Mirror", side_effect=AssertionError("mirror accessed")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["decrypt", "--source", "never-open", "--key-file", "never-open", "--output", "never-open", "--account", "demo"]), 2)

    def test_loose_key_permissions_are_rejected(self):
        self.key_file.chmod(0o644)
        with self.assertRaises(VaultError):
            self.sync()

    def test_key_path_traversal_is_rejected(self):
        data = json.loads(self.key_file.read_text());data["databases"] = {"../not-allowed.db": FAKE_KEY.hex()}
        self.key_file.write_text(json.dumps(data))
        with self.assertRaises(VaultError):
            self.sync()

    def test_rollback_journal_is_rejected(self):
        (self.source_dir / "message/message_0.db-journal").touch()
        with self.assertRaises(VaultError):
            self.sync()

    def test_overlap_is_rejected(self):
        self.mirror = Mirror(self.source_dir / "nested")
        with self.assertRaises(VaultError):
            self.sync()

    def test_failed_initial_run_can_retry(self):
        path = self.add_wal(["one", "two"]); value = path.read_bytes(); path.write_bytes(value[:-1])
        with self.assertRaises(VaultError):
            self.sync()
        path.write_bytes(value)
        self.assertEqual(self.sync()["decrypted"], 2)

    def test_explicit_full_mode_does_not_reuse(self):
        self.sync()
        self.assertEqual(self.sync(mode="full")["decrypted"], 2)

    def test_refresh_import_is_idempotent_and_updates_new_messages(self):
        from wechat_vault.cli import main
        command = ["--vault", str(self.archive.root), "refresh", "--source", str(self.source_dir),
                   "--key-file", str(self.key_file), "--output", str(self.mirror.root), "--account", "demo-account",
                   "--source-label", "synthetic-encrypted", "--confirm-source"]
        def run():
            out = io.StringIO()
            with mock.patch("wechat_vault.mirror.CommonCrypto", return_value=self.provider), contextlib.redirect_stdout(out):
                self.assertEqual(main(command), 0)
            return json.loads(out.getvalue())
        first = run()
        self.assertEqual(first["import"]["inserted"], 3)
        self.assertEqual(run()["import"]["duplicates"], 3)
        self.add_wal(["one", "two"])
        result = run()
        self.assertEqual(result["import"]["inserted"], 1)
        self.assertEqual(len(self.archive.query()["records"]), 2)

    def test_schema_failure_keeps_archive_transaction_intact(self):
        from wechat_vault.cli import main
        self.archive.import_records(iter([]), account="demo-account", source_label="initial", format_name="jsonl", notes=[])
        before = self.archive.status()
        with mock.patch("wechat_vault.mirror.CommonCrypto", return_value=self.provider), mock.patch("wechat_vault.cli.records", side_effect=VaultError("unsupported")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--vault", str(self.archive.root), "refresh", "--source", str(self.source_dir),
              "--key-file", str(self.key_file), "--output", str(self.mirror.root), "--account", "demo-account",
              "--source-label", "synthetic", "--confirm-source"]), 2)
        self.assertEqual(self.archive.status(), before)

    def test_sqlite_generated_wal_checksums_are_recognized(self):
        path = self.root / "sqlite-native.sqlite"
        with contextlib.closing(sqlite3.connect(path)) as con:
            con.execute("PRAGMA page_size=4096")
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE example(text TEXT)")
            con.execute("INSERT INTO example VALUES ('synthetic')")
            con.commit()
            copied = self.root / "sqlite-wal-copy"
            copied.write_bytes(Path(str(path) + "-wal").read_bytes())
        decoder = mock.Mock()
        result = index_wal(copied, decoder)
        self.assertGreater(result.committed_frames, 0)
        self.assertEqual(result.uncommitted_frames, 0)


    def test_committed_growth_adds_an_authenticated_page(self):
        self.sync()
        pages = self.messages(["one"])
        first = bytearray(pages[0]); first[28:32] = (4).to_bytes(4, "big")
        path = self.source_dir / "message/message_0.db-wal"
        path.write_bytes(wal_file([(1, 0, encrypted_page(bytes(first), 1, self.provider)),
                                  (4, 4, encrypted_page(bytes(PAGE), 4, self.provider))]))
        # Page 4 is unused, so SQLite rejects it as an integrity error. Reconstruction
        # still must grow correctly before that independent validation is performed.
        from wechat_vault.wal import reconstruct
        target = self.root / "growth.db"
        result = reconstruct(self.source_dir / "message/message_0.db", path, target, FAKE_KEY, self.provider)
        self.assertEqual(result["pages"], 4)
        self.assertEqual(target.stat().st_size, 4 * PAGE)

    def test_committed_growth_with_missing_page_is_rejected(self):
        page = encrypted_page(self.message_pages[-1], 3, self.provider)
        (self.source_dir / "message/message_0.db-wal").write_bytes(wal_file([(3, 5, page)]))
        with self.assertRaises(VaultError):
            self.sync()

    def test_committed_shrink_truncates_reconstruction(self):
        from wechat_vault.wal import reconstruct
        path = self.source_dir / "message/message_0.db-wal"
        path.write_bytes(wal_file([(2, 2, encrypted_page(self.message_pages[1], 2, self.provider))]))
        target = self.root / "shrink.db"
        self.assertEqual(reconstruct(self.source_dir / "message/message_0.db", path, target, FAKE_KEY, self.provider)["pages"], 2)
        self.assertEqual(target.stat().st_size, 2 * PAGE)

    def test_key_rotation_requires_reauthentication(self):
        self.sync()
        new_key = bytes(reversed(FAKE_KEY))
        data = json.loads(self.key_file.read_text())
        data["databases"]["message/message_0.db"] = new_key.hex()
        self.key_file.write_text(json.dumps(data))
        path = self.source_dir / "message/message_0.db"
        path.write_bytes(b"".join(encrypted_page(page, number + 1, self.provider, key=new_key) for number, page in enumerate(self.message_pages)))
        self.assertEqual(self.sync()["decrypted"], 1)
        self.assertEqual(self.current_messages(), ["one"])

    def test_wal_header_checksum_is_checked(self):
        path = self.add_wal(["one", "two"])
        value = bytearray(path.read_bytes()); value[24] ^= 1; path.write_bytes(value)
        with self.assertRaisesRegex(VaultError, "header checksum"):
            self.sync()

    def test_wal_salt_is_checked(self):
        path = self.add_wal(["one", "two"])
        value = bytearray(path.read_bytes()); value[40] ^= 1; path.write_bytes(value)
        with self.assertRaisesRegex(VaultError, "salt mismatch"):
            self.sync()

    def test_authenticated_invalid_sqlite_keeps_previous_current(self):
        self.sync()
        previous = self.mirror.marker.read_bytes()
        pages = list(self.message_pages)
        broken = bytearray(pages[1]); broken[0] = 255; pages[1] = bytes(broken)
        path = self.source_dir / "message/message_0.db"
        path.write_bytes(b"".join(encrypted_page(page, number + 1, self.provider) for number, page in enumerate(pages)))
        with self.assertRaises((VaultError, sqlite3.Error)):
            self.sync()
        self.assertEqual(previous, self.mirror.marker.read_bytes())

    def test_simultaneous_mirror_writers_are_refused(self):
        self.sync()
        from wechat_vault.files import write_lock
        with write_lock(self.mirror.root), self.assertRaises(VaultError):
            self.sync()

    def test_shared_metadata_file_is_refused(self):
        self.sync()
        self.mirror.marker.chmod(0o644)
        with self.assertRaises(VaultError):
            self.sync()

    def test_source_symlink_is_refused(self):
        path = self.source_dir / "message/message_0.db"
        alternate = self.root / "real-synthetic.db"
        path.rename(alternate); path.symlink_to(alternate)
        with self.assertRaises(VaultError):
            self.sync()

    def test_shm_only_change_invalidates_cached_database(self):
        self.sync()
        (self.source_dir / "message/message_0.db-shm").write_bytes(b"synthetic metadata")
        self.assertEqual(self.sync()["decrypted"], 1)

    def test_refresh_account_mismatch_precedes_source_reads(self):
        from wechat_vault.cli import main
        with mock.patch("wechat_vault.mirror.key_mapping", side_effect=AssertionError("keys opened")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--vault", str(self.archive.root), "refresh", "--source", str(self.source_dir),
                "--key-file", str(self.key_file), "--output", str(self.mirror.root), "--account", "different",
                "--source-label", "demo", "--confirm-source"]), 2)



    def grown_plaintext(self):
        path = self.root / "growing-plaintext.db"
        path.write_bytes(b"".join(self.message_pages))
        long_text = "synthetic overflow content " * 500
        with synthetic_database(path) as connection:
            connection.execute('INSERT INTO "' + ROOM + '" VALUES (9,999,1700000100,?,2,0)', (long_text,))
        raw = path.read_bytes()
        pages = [raw[position:position + PAGE] for position in range(0, len(raw), PAGE)]
        self.assertGreater(len(pages), 3)
        return path, pages, long_text

    def test_valid_sqlite_growth_with_overflow_pages(self):
        plain, pages, long_text = self.grown_plaintext()
        frames = [(index + 1, len(pages) if index == len(pages) - 1 else 0,
                   encrypted_page(page, index + 1, self.provider)) for index, page in enumerate(pages)]
        (self.source_dir / "message/message_0.db-wal").write_bytes(wal_file(frames))
        self.sync()
        self.assertEqual(self.current_messages(), ["one", long_text])

    def test_valid_sqlite_vacuum_shrink(self):
        plain, large_pages, _ = self.grown_plaintext()
        encrypted = self.source_dir / "message/message_0.db"
        encrypted.write_bytes(b"".join(encrypted_page(page, i + 1, self.provider) for i, page in enumerate(large_pages)))
        with synthetic_database(plain) as connection:
            connection.execute('DELETE FROM "' + ROOM + '" WHERE local_id=9')
        with contextlib.closing(sqlite3.connect(plain)) as connection:
            connection.execute("VACUUM")
        raw = plain.read_bytes(); pages = [raw[i:i + PAGE] for i in range(0, len(raw), PAGE)]
        self.assertLess(len(pages), len(large_pages))
        frames = [(i + 1, len(pages) if i == len(pages) - 1 else 0,
                   encrypted_page(page, i + 1, self.provider)) for i, page in enumerate(pages)]
        (self.source_dir / "message/message_0.db-wal").write_bytes(wal_file(frames))
        self.sync()
        self.assertEqual(self.current_messages(), ["one"])
        self.assertEqual((self.mirror.current() / "message/message_0.db").stat().st_size, len(raw))
