"""Read-only source collection for the requested PR consolidation; fork workbench only."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request
import zipfile

BASE = '32eeacdf7c1eba14a2abc51f4b7545b7e98afa40'
REPO = 'NousResearch/hermes-agent'
ALLOWED = (107350, 88069, 79727, 119729, 69202)

def git(*args):
    return subprocess.check_output(['git', *args])

def api(path):
    request = urllib.request.Request('https://api.github.com/repos/' + REPO + '/' + path,
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)

def fetch(sha):
    subprocess.run(['git', 'fetch', '--no-tags', '--depth=1', 'https://github.com/' + REPO + '.git', sha], check=True)

with zipfile.ZipFile('/tmp/codex-output-sources.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
    fetch(BASE)
    archive = git('archive', BASE)
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source:
            if not member.isfile() or member.size > 8 * 1024 * 1024:
                continue
            data = source.extractfile(member).read()
            try:
                data.decode('utf-8')
            except UnicodeDecodeError:
                continue
            if b'\x00' not in data:
                bundle.writestr('main/' + member.name, data)
    bundle.writestr('base.txt', BASE + '\n')
    for number in ALLOWED:
        pr = api('pulls/' + str(number))
        head, base = pr['head']['sha'], pr['base']['sha']
        fetch(head)
        fetch(base)
        bundle.writestr('metadata/' + str(number) + '.json', json.dumps(pr, indent=2))
        bundle.writestr('metadata/' + str(number) + '-commits.json', json.dumps(api('pulls/' + str(number) + '/commits?per_page=100'), indent=2))
        patch = git('diff', '--binary', base, head)
        bundle.writestr('patches/' + str(number) + '.diff', patch)
        changed = git('diff', '--name-only', '--diff-filter=ACMRT', base, head).decode().splitlines()
        for path in changed:
            data = git('show', head + ':' + path)
            try:
                data.decode('utf-8')
            except UnicodeDecodeError:
                continue
            bundle.writestr('sources/' + str(number) + '/' + path, data)
        print('Collected', number, head, len(changed), 'files')
print('Archive bytes:', Path('/tmp/codex-output-sources.zip').stat().st_size)
