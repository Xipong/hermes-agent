"""Only adapt the builder to the merged follow-up's persisted task_indexes."""
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = '\"model\", \"is_batch\", *_ROUTING_KEYS)'
new = '\"model\", \"is_batch\", \"task_indexes\", *_ROUTING_KEYS)'
assert s.count(old) == 1
s = s.replace(old, new)
old = '\"model\", \"is_batch\", \"result_delivery\", \"parent_turn_id\", *_ROUTING_KEYS)'
new = '\"model\", \"is_batch\", \"task_indexes\", \"result_delivery\", \"parent_turn_id\", *_ROUTING_KEYS)'
assert s.count(old) == 1
p.write_text(s.replace(old, new))
