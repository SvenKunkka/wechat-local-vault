"""Command-line interface. Nothing is installed or acquired automatically."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
import sys
from . import __version__
from .archive import Archive
from .errors import VaultError
from .ingest import records
from .files import locate


def default_root():
    base = Path.home() / ("Library/Application Support" if sys.platform == "darwin" else ".local/share")
    return base / "wechat-local-vault"


def parser():
    command = argparse.ArgumentParser(prog="wechat-vault", description="Offline private archive; never connects to WeChat.")
    command.add_argument("--version", action="version", version=__version__)
    command.add_argument("--vault", type=Path, default=None, help="Dedicated one-account private archive directory")
    sub = command.add_subparsers(dest="action", required=True)
    p = sub.add_parser("init", help="Initialize an empty dedicated archive")
    p.add_argument("--account", required=True)
    p = sub.add_parser("import", help="Import an explicitly selected detached source")
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--format", choices=("jsonl", "csv", "sqlite", "wechat4"), required=True)
    p.add_argument("--account", required=True)
    p.add_argument("--source-label", required=True, help="Stable label for import history; avoid private absolute paths")
    p.add_argument("--confirm-source", action="store_true", help="Confirm authorization to read the selected input")
    p.add_argument("--self-id", default="", help="Optional explicit self identifier for snapshot direction matching")
    sub.add_parser("status", help="Integrity, record counts and import freshness")
    p = sub.add_parser("conversations")
    p.add_argument("--identifiers", action="store_true")
    for action in ("history", "search", "contacts", "favorites", "moments"):
        p = sub.add_parser(action)
        if action == "history":
            p.add_argument("conversation")
        else:
            p.add_argument("--conversation")
        if action == "search":
            p.add_argument("term")
        p.add_argument("--since", help="Unix timestamp or ISO timestamp including timezone")
        p.add_argument("--until")
        p.add_argument("--limit", type=int, default=100)
        p.add_argument("--identifiers", action="store_true", help="Explicitly include internal identifiers")
    p = sub.add_parser("stats")
    p.add_argument("--conversation")
    p = sub.add_parser("pending")
    p.add_argument("--since")
    p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("export")
    p.add_argument("--conversation")
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--format", choices=("markdown", "jsonl"), default="markdown")
    p.add_argument("--limit", type=int, default=5000)
    p.add_argument("--since")
    p.add_argument("--until")
    return command


def execute(args):
    archive = Archive(args.vault if args.vault is not None else default_root())
    if args.action == "init":
        return archive.initialize(args.account)
    if args.action == "import":
        if not args.confirm_source:
            raise VaultError("Input was not opened. Explicit --confirm-source is required.")
        source = locate(args.source)
        if source == archive.root or source in archive.root.parents or archive.root in source.parents:
            raise VaultError("Source and archive directories must be separate.")
        notes = []
        stream = records(source, args.format, notes, self_id=args.self_id)
        return archive.import_records(stream, account=args.account, source_label=args.source_label,
                                      format_name=args.format, notes=notes)
    if args.action == "status":
        return archive.status()
    if args.action == "conversations":
        return archive.conversations(args.identifiers)
    if args.action == "stats":
        return archive.statistics(args.conversation)
    if args.action == "pending":
        return archive.pending(since=args.since, limit=args.limit)
    if args.action == "export":
        return archive.export(args.output, format_name=args.format, conversation=args.conversation,
                              limit=args.limit, since=args.since, until=args.until)
    categories = {"contacts": "contact", "favorites": "favorite", "moments": "moment"}
    return archive.query(category=categories.get(args.action, "message"),
                         conversation=args.conversation, term=getattr(args, "term", None),
                         since=args.since, until=args.until, limit=args.limit, identifiers=args.identifiers)


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        result = execute(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except VaultError as error:
        print("error: " + str(error), file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error, UnicodeError, ValueError, OverflowError, RecursionError):
        # Never echo raw records, paths, SQL payloads or arbitrary exception strings.
        print("error: local input or archive operation failed; no private details are printed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
