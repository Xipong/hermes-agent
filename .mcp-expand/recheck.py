"""Run the same cross-surface proof without changing untouched web formatting.
The dashboard uses ESLint, not Desktop's repository-wide Prettier preferences.
"""
from pathlib import Path

source = Path(__file__).with_name('run.py').read_text(encoding='utf-8')
old = "        results[surface + '-format'] = run(surface + '-format', ['node', rel + '/node_modules/prettier/bin/prettier.cjs', '--write', *files], cwd)"
new = """        if surface == 'desktop':
            results[surface + '-format'] = run(surface + '-format', ['node', rel + '/node_modules/prettier/bin/prettier.cjs', '--write', *files], cwd)
        else:
            new_web = [str(ROOT / name) for name in NEW if name.startswith('web/')]
            results[surface + '-format-new-files'] = run(surface + '-format-new-files', [
                'node', rel + '/node_modules/prettier/bin/prettier.cjs', '--write',
                '--semi=true', '--single-quote=false', '--trailing-comma=all', '--print-width=80', *new_web], cwd)
""".rstrip()
assert source.count(old) == 1
source = source.replace(old, new)
exec(compile(source, str(Path(__file__).with_name('run.py')), 'exec'), globals())
