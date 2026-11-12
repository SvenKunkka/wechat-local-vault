# Input format 1

All inputs must be authorized, detached, stable regular files outside the live client tree. Source access is explicit. The archive normalizes display text; it is not a raw backup.

## Canonical records

JSONL contains one object per line. CSV uses these field names as unique headers. Canonical SQLite contains a real, non-virtual `messages` table with at least `conversation`, `timestamp` and `text`; additional canonical columns are optional. Views are not imported.

| Field | Meaning |
|---|---|
| category | message (default), contact, favorite, moment |
| id | Stable ID unique across all sources within the account/category; omitted IDs are normalized-content hashes |
| conversation | Required for messages; stable conversation identifier |
| name | Display name; may reveal personal information |
| sender | Optional internal sender identifier |
| timestamp | Required for messages; Unix seconds/milliseconds or ISO timestamp **with timezone**; optional records default to 0 |
| kind | Optional content-type label |
| text | Displayable text or SQLite BLOB; explicit credentials/XML are filtered |
| direction | in, out, unknown (default) |

Example:

```json
{"category":"message","id":"demo-001","conversation":"synthetic-room","name":"Demo project","sender":"synthetic-friend","timestamp":"2026-01-01T08:00:00+08:00","kind":"text","text":"A fictional prototype discussion.","direction":"in"}
```

Unknown extra fields are ignored. Identifiers/labels are scalar strings or integers (up to 2048 characters); text is at most 1 MiB after decoding. No automatic timezone guess is made. The timestamp conversion treats integers above 100,000,000,000 as milliseconds. Use ISO timestamps for unusually distant dates.

A failed import rolls back all records and its import-history row. Re-importing an unchanged stable ID counts as a duplicate. Changed content with the same ID updates the existing record; imports do not delete records that disappear from a later source. Account labels are operator-provided namespaces, not authenticated WeChat identities.

## Experimental WeChat4-shaped plaintext directory

```text
snapshot/
  contact/contact.db
  message/message_0.db
  message/message_1.db      optional additional message files
  favorite/favorite.db     optional
  sns/sns.db               optional
```

The label “WeChat4-shaped” describes recognized synthetic table shapes, **not a tested client-version promise**.

- Contact table: `contact`, with `username` or `userName`; display name uses `remark`, `nick_name` or `alias`.
- Message tables: `Msg_<32 lowercase hexadecimal MD5 of conversation identifier>`. Required columns are `create_time` and `message_content`; optional fields include `local_id`, `server_id`/`mes_svr_id`, `local_type`, `real_sender_id`, `is_send`/`isSend`.
- Optional `Name2Id(user_name)` maps SQLite rowid to sender. Conversation mapping uses contacts and Name2Id identities. Missing mappings are reported as a gap.
- Message direction uses a valid explicit 0/1 send flag. Otherwise it uses an explicitly supplied `--self-id` only when sender resolution succeeds. Unknown stays unknown; no guessing from the current client.
- Favorite table: `fav_db_item` with `content`, optional `local_id`, `update_time`, `type`.
- Moments table: `SnsTimeLine` with `content`, optional `tid`, `user_name`, `create_time`, `type`.
- Unsupported/missing optional layouts produce a partial result with gaps. Missing core inputs, unsupported message columns, invalid SQLite or sidecars abort the whole import.
- IDs use server IDs where present; otherwise filename/table/local row identity. These fallback IDs are stable only while the source's layout and local IDs remain stable.

This program does not make a snapshot or checkpoint a database. It refuses any sidecar, including an empty one. Do not remove WAL/SHM/journal to force acceptance: obtain a correctly finalized offline snapshot elsewhere within your authorized workflow.

## Compression, XML and lossiness

UTF-8 text is accepted; binary undecodable content becomes a placeholder. Zstd is optional and bounded to 1 MiB output with an 8 MiB maximum window. Python 3.14 supports it without extra dependencies; older Python requires a separately installed optional decoder. Missing decoders stop compressed-message imports.

XML display extracts only leaf fields such as title/description/content/text, omits credential subtrees and rejects entities/DOCTYPE. Malformed or unrecognized XML becomes a placeholder. Explicit assignments such as password= and api_key= are redacted; this does not remove arbitrary personal information.

Raw XML, binary payloads, media and original secret values are **not stored for recovery**. Source files remain unchanged. Query/export JSONL is a display format with pseudonyms and is not an interchange-preserving backup.

## Resource limits

- 2 GiB per input file, 200,000 records per import.
- JSONL line/CSV field limit approximately 2 MiB; decoded text at most 1 MiB.
- SQLite row/string limit 4 MiB, at most 256 columns and 64 KiB SQL.
- Query limit 1–5,000 rows, with explicit truncation metadata.
- Export defaults to 5,000; if more records match, it refuses and asks for a narrower time range.
- Conversation list is limited to 5,000 entries.
