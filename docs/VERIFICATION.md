# Current release verification — 0.2.0

Date: 2026-11-12. All inputs and keys were synthetic. No local installation, real client/database/key/config access, process injection or system-protection changes occurred.

| Check | Result |
|---|---|
| macOS / Python 3.14.7 | 109 tests passed |
| macOS / Python 3.12.14 and 3.13.15 | 107 passed per interpreter; 2 optional stdlib-Zstd tests skipped |
| Separate-process Mac CLI smoke | 6 commands passed |
| WAL-only update smoke | 1 database rebuilt, 1 reused, 1 new message inserted and read back |
| Native AES | Public NIST AES-256-CBC encryption/decryption vector passed |
| Transaction semantics | Valid SQLite overflow growth and VACUUM shrink passed; uncommitted frames excluded |
| Test-strength experiment | Disabling all WAL commit markers in an isolated code copy caused 10 test failures |
| Independent review | Cache copy race reproduced, fixed, regression-tested and re-reviewed without remaining blockers |
| Publication-content check | Passed; runtime keys, mirror state, generations and databases excluded |

The cache regression changes the old plaintext after hash validation but before copying. The copied bytes must match the previous authenticated hash; otherwise the database rebuilds from encrypted input. This prevented the reproduced unauthenticated edit from entering the next generation.

The CLI smoke used two fictional encrypted databases and an explicit private fictional key map. It ran full decryption, unchanged incremental decryption, archive initialization, refresh, a WAL-only refresh and search readback. Source files were not modified by the application.

GitHub CI covers macOS/Linux and Python 3.11/3.14. The actual workflow result, not its configuration, is the authority for remote success. Native AES runs only on Mac; Linux protocol tests inject a test-only identity cipher unavailable in production.

Limits: no actual WeChat version or real account has been accepted. No installed SQLCipher runtime was used for cross-implementation acceptance. HMAC/page format and WAL rules follow public references, native AES has a public test vector, and generated inputs exercise the implementation; those checks do not replace real-client compatibility testing. Optional third-party zstandard remains unverified.

Reproduce without installing:

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 tools/check_release.py
```

---

# Historical 0.1.0 verification (superseded by the 0.2.0 record above)

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
