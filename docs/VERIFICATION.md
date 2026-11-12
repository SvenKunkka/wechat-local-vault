# Release verification — 0.1.0

Date: 2026-11-12. All local fixtures were synthetic. No real client, account data, keys or dependencies were accessed/installed.

| Environment / check | Result |
|---|---|
| macOS arm64, Python 3.14.7 | 67 tests passed |
| macOS arm64, Python 3.13.15 | 65 passed, 2 optional stdlib-Zstd tests skipped |
| macOS arm64, Python 3.12.14 | 65 passed, 2 optional stdlib-Zstd tests skipped |
| Separate CLI smoke run | 11 commands passed against 6 fictional records |
| Export mode | 0600; dedicated report directory 0700 |
| Publication-content check | Passed; no runtime database/key/config files included |

The tests cover private permissions, symlinks and hardlinks, no-overwrite publication, explicit-source gating, account binding, rollback, idempotency, changing sources, snapshot file-set changes, readonly SQL, sidecars, literal search, result limits, unknown-direction handling, XML/credential filtering and bounded standard-library Zstd.

The smoke run exercised init, import, status, conversations, search, contacts, favorites, moments, stats, pending and export. A documentation search example initially matched no fixture records; it was corrected to `confirm`, which matches two records, then the complete smoke run passed.

GitHub CI is configured for macOS/Linux and Python 3.11/3.14. The workflow result is the authority for those remote jobs; configuration alone is not a passing result.

Not verified locally: Python 3.11, Linux, the separately installed `zstandard` fallback, Windows, live WeChat, actual WeChat database layouts, SQLCipher decryption or key extraction. Windows, live capture and decryption are outside this release.

Reproduce without installing:

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 tools/check_release.py
```
