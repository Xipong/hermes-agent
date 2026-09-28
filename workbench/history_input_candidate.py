from pathlib import Path
import os
import subprocess

BASE = '1d60f98f546d4b902d8c355b61badd59873897a9'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE
path = Path('apps/desktop/e2e/history-navigation.spec.ts')
text = path.read_text()
old = '''      // Capture after Playwright's explicit movement to the page control. Read
      // only visible groups, so the assertion does not force skipped layout.
      await button.scrollIntoViewIfNeeded()
      await settleFrames()'''
new = '''      // Start a real wheel gesture away from either paging edge. This releases
      // the previous reading hold, as manual scrolling does, before Playwright
      // positions the page control. Programmatic scrolling alone is not intent.
      await viewport.hover({ position: { x: 10, y: 10 } })
      const delta = await viewport.evaluate(element =>
        element.scrollHeight - element.clientHeight - element.scrollTop <= 48 ? -1 : 1
      )
      await page.mouse.wheel(0, delta)
      await settleFrames()
      await button.scrollIntoViewIfNeeded()
      await settleFrames()
      await expect(button).toBeInViewport()
      // Capture only visible groups, without forcing skipped descendants.'''
assert text.count(old) == 1
path.write_text(text.replace(old, new, 1))
assert subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines() == [str(path)]
subprocess.run(['git', 'diff', '--check'], check=True)
subprocess.run(['git', 'add', str(path)], check=True)
subprocess.run(['git', '-c', 'user.name=Xipong', '-c', 'user.email=217837358+Xipong@users.noreply.github.com', 'commit', '-m', 'test(desktop): preserve reading anchors after explicit scroll gestures'], check=True)
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
dest = 'refs/heads/verify/history-input-125766'
subprocess.run(['git', 'push', '--force-with-lease=' + dest + ':', 'origin', 'HEAD:' + dest], check=True)
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    output.write('sha=' + sha + '\n')
print('CANDIDATE_SHA=' + sha)
