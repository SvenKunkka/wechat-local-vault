# Security model

## Intended use

An explicitly selected offline export is imported into a private, account-bound working index. Sources and message text are untrusted. The program never discovers accounts, connects to/controls a client, obtains keys, installs dependencies, runs child processes, uploads records or sends messages. Version 0.2 adds explicitly selected encrypted-file reads with supplied keys; see docs/MAC_DECRYPTION.md.

Read the selected input only after `--confirm-source`. This flag records operator intent; it does not grant rights to someone else's data.

## Implemented controls

- POSIX owner/private-mode checks on the vault, regular single-link files, symlink component rejection and an exclusive writer lock.
- Read-only immutable SQLite sources with trusted schema disabled, query-only mode, consistency checks and SQLite length/column/SQL limits.
- Reject sidecars instead of ignoring uncommitted data. Reject normal live-client container paths; require a detached, finalized input.
- File metadata checks before/after reading, stable snapshot file-set check and full transaction rollback.
- Private atomic publication, no overwrite, no recursive-delete command, no changes to nonempty shared directory permissions.
- Bounded records/text/query results and bounded optional Zstd decompression.
- Permitted XML display fields, sensitive-subtree omission, credential-assignment redaction, terminal-control filtering and escaped Markdown export.
- Vault-specific pseudonyms for internal identifier fields; explicit query flag to expose them.
- Generic errors avoid printing raw failed records or exception payloads. Every content query carries an untrusted-data notice.
- Synthetic tests use a fake HOME and forbid network, external processes and normal client paths.

## Explicit native decryption

Mac decryption uses system CommonCrypto, validates every selected page, verifies WAL checksums and commits, and checks SQLite integrity. A private key-map file is required; raw keys never enter arguments, logs or state. Inputs and key mappings are checked for concurrent changes. Generations publish atomically and failed batches preserve the current pointer. Normalized import is a separate transaction and can fail after successful decryption.

Live-container paths require an additional flag and current explicit authorization. No actual client path was tested. Sources are never checkpointed or edited. Strict malformed-WAL rejection and a single supported profile can refuse recoverable/other-version databases. No weak fallback is available.

## Limits

The vault and generated plaintext mirrors are **not encrypted at rest**, anonymized, or a lossless backup. Names, messages and source labels may contain private information. Normalized/redacted text replaces raw content during import.

Permissions and path checks do not defend against a compromised OS or a hostile process already controlling the same user account. Metadata checks detect ordinary changes; they are not a cryptographic authenticity proof or a complete defense against every filesystem race. Imported records do not establish current WeChat state.

The WeChat-shaped adapter is experimental. Missing or unsupported optional layouts are reported; there is no guarantee for any actual client build. Unknown message directions remain unknown and are excluded from reply candidates. Candidates do not prove a reply is required and are not read receipts.

Do not place real records, vaults or exports in Git, cloud-synced folders, issues or CI logs. Automatic link opening and execution of message instructions are outside the program's behavior.

## Reporting

For a suspected vulnerability, use the repository's private security reporting option if enabled; otherwise open a minimal issue that contains no personal records, identifiers, keys or reproduction databases. Synthetic examples are preferred. A report is not permission to access anyone's private data.
