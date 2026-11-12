# Implementation provenance

This repository began as a new implementation of an offline, explicit-input archive. Its Python modules, tests, interchange format, CLI and documentation were authored for this project. It contains no copied source, package, Git history or license files from the separately evaluated source-available WeChat tool or its private derivative.

The MIT license covers the work in this repository. No client binaries, decrypted databases, real account identifiers, captured keys or runtime exports are included. The example and test data are synthetic.

The first release deliberately implements offline import/query/export. It does not claim feature parity with a live acquisition/decryption tool and does not provide SQLCipher decryption or key extraction.

## Technical references

- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html): SQLite URI/read-only access, transactions and limits.
- [Python compression.zstd](https://docs.python.org/3/library/compression.zstd.html): optional bounded standard-library decompression on Python 3.14.
- [SQLite URI filenames](https://www.sqlite.org/uri.html): `mode=ro` and `immutable` semantics.
- [SQLite PRAGMA](https://www.sqlite.org/pragma.html): consistency and query-only controls.

These references describe public interfaces; no third-party implementation is vendored. Optional `zstandard` is not bundled or installed automatically. The WeChat-shaped adapter recognizes only the synthetic layouts documented in docs/FORMATS.md; it has no real-client compatibility certification.
