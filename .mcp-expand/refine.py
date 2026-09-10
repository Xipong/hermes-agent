"""Fork-only refinements applied before baseline/patched validation."""
from pathlib import Path
import subprocess
import sys

if sys.argv[1] == 'python':
    subprocess.run(['uv', 'sync', '--locked', '--python', '3.11', '--extra', 'dev', '--extra', 'mcp', '--extra', 'acp'], check=True)

p = Path('tests/hermes_cli/test_mcp_network_surfaces.py')
s = p.read_text(encoding='utf-8').replace('_load_server_configs', '_load_mcp_config')
s = s.replace('def test_catalog_install_action_forwards_network_and_owner(monkeypatch, client):',
              'def test_catalog_install_action_forwards_network_and_owner(monkeypatch, client, home):')
s = s.replace('    entry.install = SimpleNamespace()', '    entry.install = SimpleNamespace()\n    (home / "profiles" / "unity").mkdir(parents=True)')
p.write_text(s, encoding='utf-8')

p = Path('tests/tools/test_mcp_network_oauth.py')
s = p.read_text(encoding='utf-8')
s = s.replace('            get_manager().remove("network-fixture")', '            get_manager().evict("network-fixture")')
p.write_text(s, encoding='utf-8')

p = Path('tests/tools/test_mcp_windows.py')
s = p.read_text(encoding='utf-8').replace('            from pydantic import AnyUrl\n', '')
s = s.replace('task.session.read_resource(AnyUrl(str(resources.resources[0].uri)))', 'task.session.read_resource(str(resources.resources[0].uri))')
p.write_text(s, encoding='utf-8')
