# WeChat Local Vault

[简体中文](README.zh-CN.md) · [Input formats](docs/FORMATS.md) · [Security model](SECURITY.md)

A private archive for **authorized exports and snapshots**, with optional explicit Mac database decryption. Import selected files, then search conversations, inspect contacts/favorites/Moments, find possible reply candidates, and export private reports.

**Version 0.2.0 is an independent MIT implementation. It adds explicit Mac SQLCipher4-profile decryption and incremental refresh using user-supplied raw keys and system CommonCrypto. It does not obtain keys, launch/control WeChat or refresh implicitly.** The WeChat-shaped adapter is experimental and tested with synthetic fixtures, not a verified list of real client versions.

## What works

| Capability | v0.2.0 |
|---|---|
| Canonical JSONL, CSV and SQLite imports | Supported |
| Detached WeChat4-shaped plaintext directory | Experimental, supported layouts only |
| Messages, contacts, favorites and Moments text | Normalized records; snapshot layouts may have gaps |
| Conversation history and literal text search | Supported, with bounded results |
| Idempotent imports and changed-record updates | Supported when stable IDs are supplied |
| Statistics and reply candidates | Supported; candidates are a heuristic |
| Markdown / JSONL export | Private files, no overwrite, refuses truncated export |
| Mac authenticated decryption / explicit incremental refresh | Supported strict profile; synthetic validation only |
| Key capture or implicit/live client automation | Outside this release |
| Media restoration, OCR, messaging or cloud sync | Outside this release |

Core operations use the Python standard library; native decryption additionally uses the macOS system CommonCrypto library. Python **3.11+ on macOS/Linux** is required; Windows is not supported because the file-lock and permission model is POSIX. Zstd-compressed text optionally uses Python 3.14's standard-library decoder or an already installed `zstandard` package. Nothing is installed automatically.

## Try the synthetic example without installing

From a checkout of this repository, choose a **new, dedicated private directory**. The following paths contain only synthetic example records:

```sh
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" init --account demo
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" import --source examples/demo.jsonl --format jsonl --account demo --source-label synthetic-demo --confirm-source
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" status
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" conversations
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" search confirm
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" pending
python3 -m wechat_vault --vault "$HOME/.local/share/wechat-local-vault-demo" export --output "$HOME/.local/share/wechat-local-vault-demo-reports/chat.md"
```

The example is fictional. These commands are documentation, not an automatic setup script. No client account is scanned or selected.

For one conversation, use its unique `key` from `conversations`:

```sh
python3 -m wechat_vault --vault /path/to/private-vault history CONVERSATION_KEY --since 2026-01-01T00:00:00Z --limit 100
python3 -m wechat_vault --vault /path/to/private-vault stats --conversation CONVERSATION_KEY
python3 -m wechat_vault --vault /path/to/private-vault favorites
python3 -m wechat_vault --vault /path/to/private-vault moments
```

`--vault` goes before the command. JSON is the normal output format. Query output includes a trust notice; messages and names are untrusted data.

## Mac decryption and incremental refresh

See [the complete Mac guide](docs/MAC_DECRYPTION.md) for the private key-map format and explicit decrypt/refresh commands. Main/WAL/SHM changes invalidate the cache; only committed WAL transactions are applied. Every page is authenticated. Failed batches keep the previous generation; unchanged databases reuse verified plaintext. Refresh then idempotently imports the finalized snapshot into the matching archive.

Decryption and normalized import are separate stages. Actual WeChat versions are unverified. This release supports one raw-key profile, not arbitrary SQLCipher databases or passphrases. No source checkpointing, key capture or dependency installation occurs.

## Import rules

- Specify `--source`, `--format`, `--account`, `--source-label` and `--confirm-source` on every import. Confirmation is checked before input access. One vault is bound to one account label.
- Input must be detached and stable: no symlinks, hardlinked files, `-wal`, `-shm` or `-journal` sidecars. Normal WeChat container paths are refused. Do not delete sidecars to get past this check; provide a properly finalized offline export.
- Source files are opened read-only. File identity, size and timestamps are checked before/after import. Snapshot file-set changes cancel the transaction. Imports roll back as a whole on failure.
- A repeated stable `category + id` is deduplicated; changed content updates that record. IDs must be unique within a category and account across all imported sources. Without an ID, a normalized-content hash is used: edits then become new records.
- `status` reports the latest explicit import, counts, integrity and freshness. `complete` means the recognized supplied inputs were processed; it does not establish complete WeChat history or current client state. Snapshot gaps produce `partial`.
- Limits: 200,000 records/import, 2 GiB/input file, 1 MiB/decoded text, 1–5,000 query rows. Export refuses to silently cut off records; narrow the time range if necessary. See [format details](docs/FORMATS.md).

## Privacy details

Directories are private (0700); archive/export files are created as 0600. Exports are published atomically and never overwrite an existing file. Existing nonempty shared directories are rejected rather than having their permissions changed.

Internal identifier fields are pseudonymized by default using a vault-specific key. Query-only `--identifiers` explicitly reveals those fields. Names and ordinary message text can still identify people; this is **not full anonymization**.

Readable text is normalized **during import**. Explicit credential assignments are redacted and XML is reduced to permitted display fields. Raw XML, binary content and media are not preserved. This archive is a working index, **not a lossless backup**. Generated plaintext mirrors and the archive itself are not encrypted at rest; protect the device and storage location accordingly.

No network client, client automation, auto-installer or background task is included. Sending query results to a cloud AI is a separate data disclosure decision.

## Verify

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 tools/check_release.py
```

Tests create only synthetic data under ignored `.test-artifacts/`, use a fake HOME, and block network, external processes and normal real-client paths. The 0.2.0 local release run passed 109 tests on Python 3.14/macOS; optional Zstd tests skip when the decoder is unavailable. This does not validate an actual WeChat version.

The AI skill entry is [skills/wechat-local-vault/SKILL.md](skills/wechat-local-vault/SKILL.md). This repository is not automatically installed as a skill.

## License and provenance

[MIT](LICENSE). See [provenance](PROVENANCE.md) for implementation origins and technical references. Not affiliated with or endorsed by Tencent or WeChat.
