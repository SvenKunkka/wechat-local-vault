# Changelog

## 0.2.0 — 2026-11-12

### Added
- Mac native CommonCrypto AES-256-CBC and authenticated SQLCipher4 raw-key page decoding without installation.
- Strict committed-WAL reconstruction with checksums, page authentication, growth and shrink handling.
- Explicit private key mapping and account/source-bound immutable plaintext generations.
- File-level incremental cache covering main/WAL/SHM, keys and plaintext integrity; failed batches retain the prior current generation.
- Explicit decrypt and refresh commands; stable-ID archive updates with separate decryption/import stage reporting.
- Synthetic protocol, native AES-vector and incremental integration tests.

Actual WeChat versions remain unverified. No key capture, client automation, implicit refresh or dependency installation was added.

## 0.1.0 — 2026-11-12

### Added
- Independent MIT implementation of an offline, account-bound local archive.
- Canonical JSONL/CSV/SQLite and experimental detached WeChat-shaped plaintext inputs.
- Messages, contacts, favorites and Moments text queries, literal search, statistics, heuristic reply candidates and Markdown/JSONL export.
- Transactional idempotent import with stable IDs, source-change checks and explicit gaps.
- Private file handling, XML/credential display filtering and bounded results.
- Bilingual documentation, synthetic examples/tests and CI.

This release has no live client access, key capture, SQLCipher decryption, media recovery, auto-installation or background operation.
