"""All examples and files are synthetic. No WeChat client or account is used."""
from __future__ import annotations
import contextlib
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import unittest
from unittest import mock

REAL_HOME = Path.home()
TEST_AREA = Path(__file__).resolve().parents[1] / ".test-artifacts"
TEST_AREA.mkdir(mode=0o700, exist_ok=True)
FAKE_HOME = TEST_AREA / "fake-home"
FAKE_HOME.mkdir(mode=0o700, exist_ok=True)
os.environ["HOME"] = str(FAKE_HOME)
GUARD_EVENTS = []

def audit(event, args):
    if event in ("socket.connect", "socket.bind", "subprocess.Popen"):
        GUARD_EVENTS.append(event)
        raise PermissionError("Tests do not permit network access or external processes.")
    if event in ("open", "os.scandir", "os.listdir"):
        try:
            path = Path(os.fsdecode(args[0])).absolute()
        except (ValueError, TypeError):
            return
        forbidden = [REAL_HOME / "Library/Containers", REAL_HOME / ".config",
                     REAL_HOME / "Library/Application Support/wechat-local-vault",
                     REAL_HOME / "Library/Application Support/wechat-local-vault-safe",
                     Path("/Applications/WeChat.app")]
        if any(path == item or item in path.parents for item in forbidden):
            GUARD_EVENTS.append(event)
            raise PermissionError("Real client data is forbidden in this test suite.")

sys.addaudithook(audit)

from wechat_vault.archive import Archive
from wechat_vault.cli import main
from wechat_vault.errors import VaultError
from wechat_vault import files, ingest
from wechat_vault.model import record, epoch
from wechat_vault.text import display, markdown, decode


@contextlib.contextmanager
def synthetic_database(path):
    with contextlib.closing(sqlite3.connect(path)) as connection:
        with connection:
            yield connection

def message(identity="message-1", **updates):
    item = {"id": identity, "conversation": "demo-chat", "name": "Demo chat",
            "sender": "demo-friend", "timestamp": 1700000000, "kind": "text",
            "text": "Synthetic hello", "direction": "in"}
    item.update(updates)
    return record(item)


class Harness(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_AREA)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.archive = Archive(self.root / "vault")
        self.archive.initialize("demo-account")

    def add(self, items, **options):
        notes = options.pop("notes", [])
        return self.archive.import_records(iter(items), account=options.pop("account", "demo-account"),
                  source_label="synthetic", format_name="jsonl", notes=notes, **options)

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--vault", str(self.archive.root), *args])
        return code, out.getvalue(), err.getvalue()

    def source(self, items):
        path = self.root / "input.jsonl"
        path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items))
        return path


class Case(Harness):
    def test_permissions_are_private(self):
        self.assertEqual(stat.S_IMODE(self.archive.root.stat().st_mode), 0o700)
        for path in (self.archive.database, self.archive.marker):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_init_refuses_existing_directory(self):
        with self.assertRaises(VaultError):
            self.archive.initialize("other")
        folder = self.root / "manual"
        folder.mkdir()
        (folder / "keep").write_text("keep")
        with self.assertRaises(VaultError):
            Archive(folder).initialize("demo")
        self.assertEqual((folder / "keep").read_text(), "keep")

    def test_init_rejects_empty_account(self):
        with self.assertRaises(VaultError):
            Archive(self.root / "empty").initialize("")

    def test_idempotent_import(self):
        self.assertEqual(self.add([message()])["inserted"], 1)
        again = self.add([message()])
        self.assertEqual((again["inserted"], again["duplicates"], again["updated"]), (0, 1, 0))
        self.assertEqual(self.archive.status()["counts"], {"message": 1})

    def test_changed_stable_id_updates_one_record(self):
        self.add([message()])
        self.assertEqual(self.add([message(text="changed")])["updated"], 1)
        rows = self.archive.query()["records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "changed")

    def test_record_categories_have_separate_identity(self):
        self.add([message("one"), record({"category": "favorite", "id": "one", "text": "saved"})])
        self.assertEqual(self.archive.status()["counts"], {"message": 1, "favorite": 1})

    def test_cross_account_import_is_rejected_before_iteration(self):
        def forbidden():
            raise AssertionError("source opened")
            yield
        with self.assertRaises(VaultError):
            self.archive.import_records(forbidden(), account="another", source_label="demo", format_name="jsonl", notes=[])

    def test_import_failure_rolls_back_every_record(self):
        self.add([message("old")])
        def stream():
            yield message("new")
            raise VaultError("synthetic failure")
        with self.assertRaises(VaultError):
            self.add(stream())
        self.assertEqual(self.archive.status()["counts"]["message"], 1)
        self.assertEqual(self.archive.status()["latest_import"]["scanned"], 1)

    def test_partial_notes_are_reported(self):
        result = self.add([message()], notes=["favorite not supplied"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["gaps"], ["favorite not supplied"])

    def test_history_uses_opaque_keys_and_chronological_order(self):
        self.add([message("early"), message("later", timestamp=1700000010)])
        key = self.archive.conversations()["conversations"][0]["key"]
        result = self.archive.query(conversation=key)
        self.assertEqual([row["timestamp"] for row in result["records"]], [1700000000, 1700000010])
        self.assertNotIn("demo-friend", json.dumps(result))
        self.assertNotEqual(result["records"][0]["id"], "early")

    def test_internal_identifiers_require_explicit_option(self):
        self.add([message()])
        self.assertEqual(self.archive.query(identifiers=True)["records"][0]["sender"], "demo-friend")

    def test_ambiguous_names_do_not_guess(self):
        self.add([message("one"), message("two", conversation="other-chat")])
        with self.assertRaises(VaultError):
            self.archive.resolve("Demo chat")

    def test_literal_search_does_not_treat_wildcards_as_sql(self):
        self.add([message(text="100% literal _ marker"), message("two", text="other")])
        self.assertEqual(len(self.archive.query(term="%")["records"]), 1)
        self.assertEqual(self.archive.query(term="' OR 1=1 --")["records"], [])

    def test_search_and_time_range(self):
        self.add([message("first", text="Alpha"), message("second", text="alpha beta", timestamp=1700000010)])
        rows = self.archive.query(term="ALPHA", since=1700000001)["records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "alpha beta")

    def test_query_has_bounded_result_limit(self):
        for value in (0, -1, 5001):
            with self.assertRaises(VaultError):
                self.archive.query(limit=value)

    def test_query_reports_truncation(self):
        self.add([message("a"), message("b")])
        self.assertTrue(self.archive.query(limit=1)["truncated"])

    def test_pending_uses_only_known_incoming_direction(self):
        self.add([message("incoming"), message("unknown", conversation="other", direction="unknown")])
        self.assertEqual(len(self.archive.pending()["candidates"]), 1)
        self.add([message("reply", timestamp=1700000010, direction="out")])
        self.assertEqual(self.archive.pending()["candidates"], [])

    def test_stats_count_kinds_and_directions(self):
        self.add([message(), message("out", direction="out", kind="image")])
        result = self.archive.statistics()
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["breakdown"]), 2)

    def test_favorites_contacts_and_moments_query(self):
        items = [record({"category": kind, "id": kind, "name": "demo", "text": "synthetic"}) for kind in ("contact", "favorite", "moment")]
        self.add(items)
        for command in ("contacts", "favorites", "moments"):
            code, out, err = self.cli(command)
            self.assertEqual(code, 0, err)
            self.assertEqual(len(json.loads(out)["records"]), 1)

    def test_export_private_and_no_overwrite(self):
        self.add([message()])
        path = self.root / "exports/chat.md"
        self.archive.export(path)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertIn("Synthetic hello", path.read_text())
        with self.assertRaises(VaultError):
            self.archive.export(path)

    def test_export_rejects_truncated_data_without_writing(self):
        self.add([message("one"), message("two")])
        path = self.root / "out/chat.jsonl"
        with self.assertRaises(VaultError):
            self.archive.export(path, format_name="jsonl", limit=1)
        self.assertFalse(path.exists())

    def test_jsonl_export_is_valid(self):
        self.add([message()])
        path = self.root / "out/chat.jsonl"
        self.archive.export(path, format_name="jsonl")
        self.assertEqual(json.loads(path.read_text())["text"], "Synthetic hello")

    def test_source_confirmation_precedes_source_access(self):
        with mock.patch("wechat_vault.cli.locate", side_effect=AssertionError("input accessed")):
            code, _, err = self.cli("import", "--source", "/not-opened", "--format", "jsonl",
                                    "--account", "demo-account", "--source-label", "demo")
        self.assertEqual(code, 2)
        self.assertIn("--confirm-source", err)

    def test_jsonl_cli_import_and_source_unchanged(self):
        source = self.source([message()])
        before = source.read_bytes()
        code, out, err = self.cli("import", "--source", str(source), "--format", "jsonl",
                      "--account", "demo-account", "--source-label", "demo", "--confirm-source")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["inserted"], 1)
        self.assertEqual(source.read_bytes(), before)

    def test_invalid_json_is_private_and_atomic(self):
        source = self.source([message()])
        with source.open("a") as stream:
            stream.write("PRIVATE_INVALID_PAYLOAD\n")
        code, _, err = self.cli("import", "--source", str(source), "--format", "jsonl",
                      "--account", "demo-account", "--source-label", "demo", "--confirm-source")
        self.assertEqual(code, 2)
        self.assertNotIn("PRIVATE_INVALID_PAYLOAD", err)
        self.assertEqual(self.archive.status()["counts"], {})

    def test_source_mutation_aborts_import(self):
        source = self.source([message()])
        stream = ingest.json_lines(source, [])
        def changing():
            yield next(stream)
            with source.open("a") as handle:
                handle.write("\n")
            yield from stream
        with self.assertRaises(VaultError):
            self.add(changing())
        self.assertEqual(self.archive.status()["counts"], {})

    def test_csv_import(self):
        source = self.root / "input.csv"
        with source.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(message()))
            writer.writeheader()
            writer.writerow(message())
        result = self.add(ingest.csv_rows(source, []))
        self.assertEqual(result["inserted"], 1)

    def test_canonical_sqlite_import(self):
        source = self.root / "input.sqlite"
        with synthetic_database(source) as con:
            con.execute("CREATE TABLE messages(id TEXT,conversation TEXT,timestamp INTEGER,text TEXT)")
            con.execute("INSERT INTO messages VALUES ('example','chat',1700000000,'synthetic')")
        before = source.read_bytes()
        self.assertEqual(self.add(ingest.canonical_sqlite(source, []))["inserted"], 1)
        self.assertEqual(source.read_bytes(), before)

    def test_readonly_source_cannot_be_modified(self):
        source = self.root / "input.sqlite"
        with synthetic_database(source) as con:
            con.execute("CREATE TABLE demo(text TEXT)")
        with files.sqlite_input(source) as con:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("INSERT INTO demo VALUES ('forbidden')")

    def test_sqlite_sidecars_are_not_ignored(self):
        source = self.root / "input.sqlite"
        source.touch()
        for ending in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(source) + ending)
            sidecar.touch()
            with self.subTest(ending=ending), self.assertRaises(VaultError):
                files.detached(source)
            sidecar.unlink()

    def test_symlink_input_is_rejected(self):
        source = self.source([message()])
        link = self.root / "linked.jsonl"
        link.symlink_to(source)
        with self.assertRaises(VaultError):
            self.add(ingest.json_lines(link, []))

    def test_symlink_output_is_rejected(self):
        self.add([message()])
        original = self.root / "original"
        original.write_text("preserve")
        link = self.root / "linked"
        link.symlink_to(original)
        with self.assertRaises(VaultError):
            self.archive.export(link)
        self.assertEqual(original.read_text(), "preserve")

    def test_parent_symlink_output_is_rejected(self):
        target = self.root / "target"
        target.mkdir()
        linked = self.root / "linked-dir"
        linked.symlink_to(target, target_is_directory=True)
        with self.assertRaises(VaultError):
            files.publish(linked / "new.md", "test")

    def test_hardlink_vault_is_rejected(self):
        backup = self.root / "duplicate"
        os.link(self.archive.database, backup)
        with self.assertRaises(VaultError):
            self.archive.status()

    def test_loose_vault_permissions_are_rejected(self):
        self.archive.database.chmod(0o644)
        with self.assertRaises(VaultError):
            self.archive.status()

    def test_concurrent_writers_are_rejected(self):
        with files.write_lock(self.archive.root):
            with self.assertRaises(VaultError):
                self.add([message()])

    def test_source_and_archive_must_not_overlap(self):
        code, _, _ = self.cli("import", "--source", str(self.archive.root), "--format", "wechat4",
                             "--account", "demo-account", "--source-label", "demo", "--confirm-source")
        self.assertEqual(code, 2)

    def test_live_container_path_is_rejected_without_open(self):
        with self.assertRaises(VaultError):
            files.detached(self.root / "Containers/com.tencent.xinWeChat/Data/fake.db")

    def test_bad_timestamp_is_rejected(self):
        for value in (True, -1, "2026-01-01", "not-a-time", 10**30):
            with self.subTest(value=value), self.assertRaises(VaultError):
                epoch(value, required=True)
        self.assertEqual(epoch("2026-01-01T08:00:00+08:00"), epoch("2026-01-01T00:00:00Z"))

    def test_unknown_direction_and_category_are_rejected(self):
        with self.assertRaises(VaultError):
            message(direction="maybe")
        with self.assertRaises(VaultError):
            record({"category": "execute", "text": "no"})

    def test_text_size_is_bounded(self):
        with self.assertRaises(VaultError):
            display("x" * (1024 * 1024 + 1))

    def test_xml_allowlist_hides_transport_credentials(self):
        text = display("<msg><title>Readable title</title><aeskey>DO_NOT_DISPLAY</aeskey><fileid>PRIVATE_FILE</fileid></msg>")
        self.assertEqual(text, "Readable title")
        self.assertNotIn("DO_NOT_DISPLAY", text)

    def test_xml_entities_are_rejected(self):
        self.assertEqual(display('<!DOCTYPE a [<!ENTITY b "expand">]><msg>&b;</msg>'), "[unsafe XML omitted]")

    def test_malformed_xml_does_not_leak_original(self):
        self.assertEqual(display("<msg>SECRET_BROKEN"), "[unrecognized XML omitted]")

    def test_plain_credentials_are_redacted(self):
        text = display('api_key="FAKE_ONE" password=FAKE_TWO token=FAKE_THREE')
        for secret in ("FAKE_ONE", "FAKE_TWO", "FAKE_THREE"):
            self.assertNotIn(secret, text)

    def test_markdown_cannot_embed_images_or_html(self):
        text = markdown('![image](https://example.invalid) <script>ignored</script>')
        self.assertNotIn("![image]", text)
        self.assertNotIn("<script>", text)

    def test_terminal_controls_are_removed(self):
        self.assertNotIn("\x1b", display("hello\x1b[31m"))

    def test_status_has_explicit_freshness(self):
        self.assertIn("no live-client refresh", self.archive.status()["freshness"])

    def test_cli_sanitizes_database_errors(self):
        self.archive.database.write_bytes(b"SECRET_INVALID_DATABASE")
        code, _, err = self.cli("status")
        self.assertEqual(code, 2)
        self.assertNotIn("SECRET_INVALID_DATABASE", err)

    def test_default_help_does_not_initialize_a_vault(self):
        from wechat_vault.cli import default_root
        before = default_root().exists()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            main(["--help"])
        self.assertEqual(default_root().exists(), before)


    def test_prefixed_xml_is_filtered_instead_of_printed_raw(self):
        text = display('demo-sender:\n<msg><title>Visible</title><aeskey>HIDDEN_CREDENTIAL</aeskey></msg>')
        self.assertEqual(text, "Visible")
        self.assertNotIn("HIDDEN_CREDENTIAL", text)

    def test_sensitive_xml_subtrees_are_not_extracted(self):
        self.assertEqual(display("<msg><title>Visible</title><aeskey><title>HIDDEN</title></aeskey></msg>"), "Visible")

    def test_duplicate_csv_headers_are_rejected(self):
        source = self.root / "duplicate.csv"
        source.write_text("text,text\nfirst,second\n")
        with self.assertRaises(VaultError):
            self.add(ingest.csv_rows(source, []))

    def test_sqlite_views_are_not_imported_as_tables(self):
        source = self.root / "view.sqlite"
        with synthetic_database(source) as con:
            con.execute("CREATE VIEW messages AS SELECT 'chat' AS conversation,1700000000 AS timestamp,'text' AS text")
        with self.assertRaises(VaultError):
            self.add(ingest.canonical_sqlite(source, []))

    def test_invalid_metadata_reports_a_safe_error(self):
        self.archive.marker.write_text("[]")
        code, _, err = self.cli("status")
        self.assertEqual(code, 2)
        self.assertIn("metadata", err)

    def test_export_does_not_chmod_unrelated_shared_directory(self):
        directory = self.root / "shared"
        directory.mkdir(mode=0o755)
        (directory / "manual.txt").write_text("preserve")
        with self.assertRaises(VaultError):
            self.archive.export(directory / "chat.md")
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755)

    def test_fallback_conversation_name_hides_identifier(self):
        self.add([message(name="demo-chat")])
        self.assertEqual(self.archive.conversations()["conversations"][0]["name"], "[identifier hidden]")



class SnapshotCase(Harness):
    # Reuse the isolated harness, but do not inherit all generic tests twice.
    def snapshot(self):
        root = self.root / "snapshot"
        for name in ("contact", "message", "favorite", "sns"):
            (root / name).mkdir(parents=True)
        with synthetic_database(root / "contact/contact.db") as con:
            con.execute("CREATE TABLE contact(username TEXT, remark TEXT)")
            con.executemany("INSERT INTO contact VALUES (?,?)", [("demo-room", "Synthetic group"), ("demo-friend", "Synthetic friend")])
        table = "Msg_" + hashlib.md5(b"demo-room").hexdigest()
        with synthetic_database(root / "message/message_0.db") as con:
            con.execute("CREATE TABLE Name2Id(user_name TEXT)")
            con.executemany("INSERT INTO Name2Id VALUES (?)", [("demo-self",), ("demo-friend",), ("demo-room",)])
            con.execute('CREATE TABLE "' + table + '"(local_id INTEGER,server_id INTEGER,create_time INTEGER,local_type INTEGER,message_content BLOB,real_sender_id INTEGER)')
            con.execute('INSERT INTO "' + table + '" VALUES (1,123,1700000000,1,?,2)', ("Synthetic source message",))
        with synthetic_database(root / "favorite/favorite.db") as con:
            con.execute("CREATE TABLE fav_db_item(local_id INTEGER, update_time INTEGER,content TEXT)")
            con.execute("INSERT INTO fav_db_item VALUES (1,1700000000,'Saved synthetic note')")
        with synthetic_database(root / "sns/sns.db") as con:
            con.execute("CREATE TABLE SnsTimeLine(tid TEXT,user_name TEXT,create_time INTEGER,content TEXT)")
            con.execute("INSERT INTO SnsTimeLine VALUES ('post','demo-friend',1700000000,'<msg><content>Synthetic moment</content></msg>')")
        return root

    def test_wechat_shaped_snapshot_all_categories(self):
        source = self.snapshot()
        before = {str(p): p.read_bytes() for p in source.rglob("*.db")}
        notes = []
        report = self.add(ingest.wechat_snapshot(source, notes, self_id="demo-self"), notes=notes)
        self.assertEqual(report["inserted"], 5)
        self.assertEqual(report["gaps"], [])
        self.assertEqual(self.archive.query()["records"][0]["text"], "Synthetic source message")
        self.assertEqual(len(self.archive.pending()["candidates"]), 1)
        self.assertEqual(before, {str(p): p.read_bytes() for p in source.rglob("*.db")})

    def test_missing_optional_databases_are_reported(self):
        source = self.snapshot()
        (source / "favorite/favorite.db").unlink()
        notes = []
        report = self.add(ingest.wechat_snapshot(source, notes), notes=notes)
        self.assertEqual(report["status"], "partial")
        self.assertIn("favorite: database not supplied", report["gaps"])

    def test_missing_core_schema_does_not_guess(self):
        source = self.root / "empty-snapshot"
        source.mkdir()
        with self.assertRaises(VaultError):
            self.add(ingest.wechat_snapshot(source, []))

    def test_snapshot_with_unmerged_wal_is_refused(self):
        source = self.snapshot()
        (source / "message/message_0.db-wal").touch()
        with self.assertRaises(VaultError):
            self.add(ingest.wechat_snapshot(source, []))
        self.assertEqual(self.archive.status()["counts"], {})

    def test_unknown_self_leaves_direction_unknown(self):
        source = self.snapshot()
        self.add(ingest.wechat_snapshot(source, []))
        self.assertEqual(self.archive.query()["records"][0]["direction"], "unknown")
        self.assertEqual(self.archive.pending()["candidates"], [])



    def test_snapshot_file_set_change_rolls_back(self):
        source = self.snapshot()
        stream = ingest.wechat_snapshot(source, [])
        def changing():
            yield next(stream)
            (source / "message/message_1.db").touch()
            yield from stream
        with self.assertRaises(VaultError):
            self.add(changing())
        self.assertEqual(self.archive.status()["counts"], {})

    def test_invalid_is_send_does_not_guess_incoming(self):
        source = self.snapshot()
        with synthetic_database(source / "message/message_0.db") as con:
            table = "Msg_" + hashlib.md5(b"demo-room").hexdigest()
            con.execute('ALTER TABLE "' + table + '" ADD COLUMN is_send INTEGER DEFAULT 2')
        self.add(ingest.wechat_snapshot(source, [], self_id="demo-self"))
        self.assertEqual(self.archive.query()["records"][0]["direction"], "unknown")



class CompressionCase(unittest.TestCase):
    def test_bounded_standard_library_zstd(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest("Python 3.14 optional standard-library zstd is unavailable")
        blob = zstd.compress("Synthetic compressed message".encode())
        self.assertEqual(decode(blob), "Synthetic compressed message")
        with self.assertRaises(VaultError):
            decode(zstd.compress(b"x" * (1024 * 1024 + 1)))

    def test_corrupt_zstd_returns_safe_error(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest("Optional stdlib zstd is unavailable")
        with self.assertRaises(VaultError):
            decode(b"\x28\xb5\x2f\xfd" + b"invalid frame")

    def test_no_network_or_real_source_guard_events(self):
        self.assertEqual(GUARD_EVENTS, [])


if __name__ == "__main__":
    unittest.main()
