# Canonical encoding mechanisms

The Python default profile is signed int64, no floats, maximum depth 64.
`LIBRARY_JSON_PROFILE` preserves the historical Library acceptance of finite
floats, unbounded integers and depth 32. `decode_json` uses the strict profile
and rejects duplicate object keys and non-finite values. Owners select payloads,
prefixes and array/collection order; infrastructure does not infer them.

The JavaScript `stableJSON`/`jsonDigest` implementation is a partial mirror.
Cross-language golden vectors cover finite safe integers, ordinary string-key
ordering, nested objects, dense arrays, Unicode strings and escaped controls.
Neither implementation normalizes Unicode. SHA-256 hashes their actual UTF-8
bytes. JavaScript rejects non-finite values, cycles, non-plain objects and sparse
arrays (including holes disguised by named properties).

Full acceptance and byte equivalence is **not** established: Python supports
int64 values outside JS's exact safe integer range; JS accepts finite floats and
has no Python depth bound; JS sorts keys by UTF-16 whereas Python sorts by Unicode
code points, so non-BMP/BMP key pairs can differ. Library float rendering also
differs (for example Python `1.0` versus JS `1`, and Python `-0.0` versus JS `0`).
Consumers needing exact cross-language hashes must restrict their input domain
or obtain an explicitly versioned owner decision; no historical bytes or digest
normalization has been silently changed here. Lone-surrogate handling is not a
unified cross-language contract either.
