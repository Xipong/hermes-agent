from __future__ import annotations

import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
api = root / "web/src/lib/api.ts"
config = root / "cli-config.yaml.example"

api_text = api.read_text(encoding="utf-8")
api_lines = api_text.splitlines()
print("api lines", len(api_lines))
marker = "/** Identity payload returned by ``GET /api/auth/me``"
print("type-tail marker", api_text.index(marker), "line", api_text[: api_text.index(marker)].count("\n") + 1)

tail = api_text[api_text.index(marker):]
exports = re.findall(r"^export\s+(interface|type|enum|class|const|function)\s+([A-Za-z_$][\w$]*)", tail, re.M)
print("tail export kinds", {kind: sum(1 for k, _ in exports if k == kind) for kind, _ in exports})
print("tail export count", len(exports))
print("tail non-type exports", [(kind, name) for kind, name in exports if kind not in {"interface", "type"}])
print("first exports", exports[:30])
print("last exports", exports[-30:])

imports = []
pattern = re.compile(r"import\s+(?:type\s+)?\{.*?\}\s+from\s+['\"]@/lib/api['\"];?", re.S)
for path in sorted((root / "web/src").rglob("*.ts*")):
    text = path.read_text(encoding="utf-8")
    for match in pattern.finditer(text):
        imports.append((str(path.relative_to(root)), match.group(0).replace("\n", " ")))
print("imports from api", len(imports), "files", len({p for p, _ in imports}))
for path, statement in imports:
    print("IMPORT", path, statement[:500])

config_lines = config.read_text(encoding="utf-8").splitlines()
print("config lines", len(config_lines))
blocks = []
i = 0
while i < len(config_lines):
    if not config_lines[i].lstrip().startswith("#"):
        i += 1
        continue
    start = i
    while i < len(config_lines) and (config_lines[i].lstrip().startswith("#") or not config_lines[i].strip()):
        i += 1
    comments = [line for line in config_lines[start:i] if line.lstrip().startswith("#")]
    if len(comments) >= 4:
        heading = next((line.lstrip("# ") for line in comments if line.lstrip("# ")), "")
        blocks.append((len(comments), start + 1, i, heading[:120]))
print("comment blocks >=4", len(blocks))
for item in sorted(blocks, reverse=True)[:80]:
    print("BLOCK", item)
