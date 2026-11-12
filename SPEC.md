# Independent release specification — 0.1.0

Objective: publish SvenKunkka/wechat-local-vault as a public MIT repository containing newly authored implementation, tests, skill instructions and bilingual documentation. Retain the restricted upstream and private derivative untouched. No installation or real WeChat data access during development.

Modules: guarded local files → bounded normalized/import adapters → transactional account vault → CLI query/export → synthetic tests and documentation. One standard-library Python package; Python 3.11+ on macOS/Linux. Optional compressed source support through Python3.14 compression.zstd or separately installed zstandard. No automatic dependencies.

Acceptance:
- Explicit confirmation before opening any user-selected input. Never discover client accounts or open a running client's storage.
- Import canonical JSONL, canonical CSV, canonical messages SQLite and explicitly detached WeChat4-shaped plaintext snapshot directories. Message/contact/favorite/moment records; report schema gaps.
- Private vault and outputs, no source writes, no active sidecars or links, no overwrite exports, bounded parsing, all-or-nothing import, idempotent stable external IDs, single-account binding.
- Conversations, history, literal search, contacts/favorites/moments, statistics, heuristic reply candidates, private Markdown/JSONL exports.
- Source signatures before/after import and read-only SQLite. Unknown formats fail visibly, no speculative decoding.
- Preserve untrusted-data boundaries and remove explicit credential fields from display. This is not complete anonymization.
- No key extraction, SQLCipher decryption, application copying/re-signing, system protection changes, live database acquisition, cloud upload, background jobs, messages or deletion commands in this first release.
- Tests use synthetic fixtures, fake HOME and audit guards; no network or app launches. Verify package and public repository readback.
- README.md (English), README.zh-CN.md (Chinese), LICENSE MIT, SECURITY.md, skill entry, format specification, provenance, changelog and GitHub CI.
Commands: python3 -m unittest discover -s tests -v; python3 -m wechat_vault --help; python3 tools/check_release.py.
No mandatory user decisions remain: independent public route and publishing authorization already given.

## 0.2.0 extension: Mac authenticated decryption and incremental refresh

Authorized scope: implement independently and retain MIT; validate only synthetic files. No local installs or real client/key/config reads. Existing permission to publish this public project continues.

- Native macOS CommonCrypto via ctypes; no dependency installation, process hooks or key extraction. Raw 32-byte keys are supplied in an explicit private JSON mapping, never command-line values, logs, output state or Git.
- One strict SQLCipher4 profile: 4096-byte pages, 80 reserved bytes, AES-256-CBC, 16-byte salt, HMAC-SHA512 with a separately derived key; reject other profiles and wrong/tampered pages. Public technical specifications inform new code; no restricted tool source is reused.
- Explicit database allowlist in the key file, explicit account/source/output and confirmation. Read only selected regular files and their WAL/SHM metadata, reject rollback journals and source/output overlaps. Real/live container access requires an additional explicit command flag; development/tests never supply real inputs.
- Validate both WAL checksum byte orders and header/frame salts, authenticate frames, apply only transactions through the last complete commit, handle growth/shrink, and fail closed on malformed tails. Stable captures recheck identity/metadata and the selected file set before publication; no checkpoint/source writes.
- Atomic pointer to an immutable private output generation; full-batch failure keeps the prior current generation. Incremental fingerprints include main/WAL/SHM, key and cached plaintext integrity. Unchanged files copy verified plaintext; changed files rebuild fully. This is file-level incremental decryption, not page-level delta storage.
- Refresh explicitly decrypts and idempotently imports the current finalized plaintext snapshot into the matching account archive. Import failure leaves the prior archive transaction intact; decryption generation and normalized archive are separately reported stages.
- Synthetic tests cover native AES against a public NIST vector, authenticated pages, wrong keys/tampering, WAL-only new messages, uncommitted tails, checksum/salt errors, shrink/growth/gaps, rotation, cache damage, source mutations, permissions, scope gates, account mismatches and rollback. Linux protocol tests use an injected test-only cipher; production native AES is Mac-only.
- No auto-refresh during queries, key capture, installation, client automation, media recovery, weak-auth fallback, source cleanup or real-client compatibility claim.

Implementation order: native/page profile → WAL reconstruction → generation/caching → CLI refresh → synthetic integration/regression → documentation/release checks and public CI. Commands remain unittest discover, check_release, and synthetic CLI smoke. Success requires all appropriate local checks and the public Mac/Linux CI matrix to pass before marking the release complete.
