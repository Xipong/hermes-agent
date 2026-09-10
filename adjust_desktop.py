from pathlib import Path
p = Path('apps/desktop/src/app/skills/store.ts')
s = p.read_text()
for name in ('SKILLS_QUERY_KEY', 'TOOLSETS_QUERY_KEY'):
    old = f'const {name} ='
    assert s.count(old) == 1 and f'export {old}' not in s
    s = s.replace(old, f'export {old}')
p.write_text(s)
