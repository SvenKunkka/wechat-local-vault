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
