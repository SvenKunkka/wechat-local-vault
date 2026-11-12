# Implementation provenance

This repository began as a new implementation of an offline, explicit-input archive. Its Python modules, tests, interchange format, CLI and documentation were authored for this project. It contains no copied source, package, Git history or license files from the separately evaluated source-available WeChat tool or its private derivative.

The MIT license covers the work in this repository. No client binaries, decrypted databases, real account identifiers, captured keys or runtime exports are included. The example and test data are synthetic.

Version 0.1.0 deliberately implemented offline import/query/export without decryption. Version 0.2.0 adds the independently written native extension described below. Key extraction remains outside the project.

## Technical references

- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html): SQLite URI/read-only access, transactions and limits.
- [Python compression.zstd](https://docs.python.org/3/library/compression.zstd.html): optional bounded standard-library decompression on Python 3.14.
- [SQLite URI filenames](https://www.sqlite.org/uri.html): `mode=ro` and `immutable` semantics.
- [SQLite PRAGMA](https://www.sqlite.org/pragma.html): consistency and query-only controls.

These references describe public interfaces; no third-party implementation is vendored. Optional `zstandard` is not bundled or installed automatically. The WeChat-shaped adapter recognizes only the synthetic layouts documented in docs/FORMATS.md; it has no real-client compatibility certification.

## 0.2.0 native decryption extension

The page-profile, WAL reconstruction, native adapter and generation cache were newly written for this project. Public SQLCipher/SQLite format facts and constants were cross-checked against official design/API descriptions and the SQLCipher upstream protocol implementation; none of that implementation is vendored or copied.

Additional references: [SQLCipher design](https://www.zetetic.net/sqlcipher/design/), [SQLCipher API](https://www.zetetic.net/sqlcipher/sqlcipher-api/), [SQLCipher protocol reference](https://github.com/sqlcipher/sqlcipher/blob/master/src/sqlcipher.c), [SQLite file/WAL format](https://sqlite.org/fileformat2.html), [Apple CommonCrypto CCCrypt](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/CCCrypt.3cc.html), [NIST AES-CBC test vectors](https://csrc.nist.gov/CSRC/media/Projects/Cryptographic-Standards-and-Guidelines/documents/examples/AES_CBC.pdf).

The operating system supplies AES; Python's standard library supplies SHA-512/HMAC/PBKDF2. No crypto implementation or client binary is bundled. Tests use fictional generated databases; the NIST vector is public standards test data.
