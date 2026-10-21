import json
def canonical_json(value): return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
