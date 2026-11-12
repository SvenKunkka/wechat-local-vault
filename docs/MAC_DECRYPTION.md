# Mac decryption and incremental refresh — 0.2.0

This feature reads **only explicitly selected databases using user-supplied raw keys**. It does not find keys, inspect process memory, launch/re-sign WeChat, change SIP, install anything, checkpoint or modify sources.

Development and release validation used generated databases only. No real WeChat account or version has been accepted.

## Supported profile

`sqlcipher4-4096-raw` is intentionally strict:

- 4096-byte pages; 80 reserved bytes (16-byte IV + 64-byte authentication tag).
- 32-byte raw AES key, AES-256-CBC without padding; the first 16 database bytes are the salt.
- Separate HMAC key: PBKDF2-HMAC-SHA512, 2 iterations, 32 bytes, using the raw encryption key and salt bytes XOR 0x3a.
- Each page authenticates ciphertext + IV + little-endian page number with HMAC-SHA512 before decryption.
- First-page salt/layout validation and full SQLite integrity_check.
- Native AES uses macOS CommonCrypto through Python ctypes. No Python crypto package, SQLCipher executable or downloaded dependency is required.

This is a page-format reader, not the SQLCipher runtime. It supports neither passphrases nor older/nondefault profiles, plaintext-header variants, unauthenticated all-zero pages, custom HMAC settings or encrypted rollback journals. Unsupported inputs fail instead of falling back to weak checks.

## Explicit key mapping

Keep the mapping in an **owned regular 0600 file**, outside both source and generated directories. Keys are supplied here, never as command-line values. A template follows; replace placeholders locally only:

```json
{
  "account": "your-local-account-label",
  "profile": "sqlcipher4-4096-raw",
  "databases": {
    "contact/contact.db": "REPLACE_WITH_64_HEXADECIMAL_CHARACTERS",
    "message/message_0.db": "REPLACE_WITH_64_HEXADECIMAL_CHARACTERS"
  }
}
```

Each key entry selects exactly one relative .db file. No wildcard, recursive account discovery or default original-tool configuration is used. At most 256 databases are selected. Add favorites/SNS entries only when explicitly authorized and their keys are known.

The account label is a local namespace, not proof of a WeChat identity. Changing the selected set replaces that generation's selection; normalized records absent from a later source are not deleted from the archive.

Raw keys are not persisted in mirror metadata, results, logs or exports. Metadata contains a private random cache secret and keyed cache fingerprints, not the supplied keys. Python/provider memory cannot be reliably wiped; the native temporary buffers are cleared after a call.

## Commands (documentation only)

Choose separate dedicated source, key, mirror and normalized-archive locations:

```sh
python3 -m wechat_vault decrypt --source /path/to/authorized-encrypted-copy --key-file /path/to/private-key-map.json --output /path/to/private-mirror --account your-local-account-label --confirm-source --mode full
python3 -m wechat_vault decrypt --source /path/to/authorized-encrypted-copy --key-file /path/to/private-key-map.json --output /path/to/private-mirror --account your-local-account-label --confirm-source --mode incremental

python3 -m wechat_vault --vault /path/to/private-archive init --account your-local-account-label
python3 -m wechat_vault --vault /path/to/private-archive refresh --source /path/to/authorized-encrypted-copy --key-file /path/to/private-key-map.json --output /path/to/private-mirror --account your-local-account-label --source-label selected-mac-source --confirm-source --mode incremental
```

`decrypt` updates the private plaintext mirror only. `refresh` also imports the current generation through the existing WeChat-shaped adapter. A source-schema gap can yield a partial import even when all selected databases decrypted successfully.

Common live-client container paths are refused by default. A future operator with explicit authorization may add `--allow-live-source` for one specifically named source. This flag does not launch or control the client, capture keys, make a cross-database atomic snapshot or authorize anyone else's data. Live writes can make a capture fail. No real source was used to test this flag.

Queries never refresh implicitly. Every future refresh requires the explicit source/key/account flags again.

## WAL and consistency

The main database and selected sidecars are fingerprinted before/after capture, including inode, size, mtime and ctime. WAL and SHM changes invalidate the cache. The key file is checked for changes as well. Rollback journals are refused; SHM is observed, never modified or used as a substitute for WAL validation.

WAL parsing validates the header, version, page size, both SQLite checksum byte orders, frame salts, cumulative checksums and page authentication. Only frames through the last complete commit affect the result. Valid uncommitted frames are counted and excluded. Growth, truncation and repeated page updates are handled; missing pages cause failure.

Malformed/truncated frames, bad checksums and stale/reset tails are rejected. This strict policy can refuse a WAL that SQLite would partially recover. It never labels that fallback as current data.

Sources are copied read-only into private temporary capture files and rechecked before publication. This detects ordinary concurrent writes; it does not prove a globally atomic point in time across multiple independent databases. No source checkpoint, sidecar deletion or client lock manipulation occurs.

## Incremental semantics

- The first run authenticates/decrypts every selected file.
- A later run reuses a prior plaintext file only when source/sidecar metadata and the keyed raw-key fingerprint match and the cached plaintext hash verifies.
- Reused files are copied into the next generation; changed files are rebuilt and authenticated in full.
- A damaged/missing cache rebuilds from encrypted input. An incorrect key or damaged source aborts publication.
- Refresh re-imports the finalized snapshot transactionally. Stable IDs deduplicate unchanged records and update edited records. This rescans recognized records; it is not a message-cursor or page-delta algorithm.

One private metadata pointer publishes the complete immutable generation atomically. A batch failure leaves the previous pointer and its plaintext intact. Staging files created by the failed run are removed; prior generations and all source files are retained. No automatic generation cleanup is included, so repeated generations consume disk space.

Decryption publication and normalized archive import are **separate transactions**. If the latter fails, a new valid plaintext generation may exist while the old archive remains unchanged. The CLI returns an error that identifies this distinction.

## Test evidence

The new tests use fictional keys and generated SQLite files with 80 reserved bytes. They cover native AES against the NIST AES-256-CBC vector, authenticated pages, WAL-only updates, uncommitted tails, both checksum orders, actual SQLite-emitted WAL checksums, valid overflow-page growth and VACUUM shrink, rotation, cache damage, concurrent mutation, account gates and failure rollback.

Mac tests use real system CommonCrypto on synthetic data. Linux protocol tests inject a test-only identity cipher; production does not expose that fallback, and the native AES vector test skips on Linux. A passing simulation does not establish compatibility with any real WeChat build.

Public format references: [SQLCipher design](https://www.zetetic.net/sqlcipher/design/), [SQLCipher key/API](https://www.zetetic.net/sqlcipher/sqlcipher-api/), [SQLite WAL](https://sqlite.org/fileformat2.html#walformat), [Apple CCCrypt](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/CCCrypt.3cc.html), [NIST CBC vectors](https://csrc.nist.gov/CSRC/media/Projects/Cryptographic-Standards-and-Guidelines/documents/examples/AES_CBC.pdf).
