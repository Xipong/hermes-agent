import sys
import history_fix as task

# Add the shared locale contract alongside all nine translated dictionaries.
task.EDITS['apps/desktop/src/i18n/types.ts'] = {
    'sha256': '12846f52f163e684032aba0d6422195c341aa35410316f7d87eff3998d4b7353',
    'edits': [[4235, 4235, '      showLater: string\n      jumpToLatest: string\n      historyLoadFailed: string\n      historyPagingUnavailable: string\n']],
}

original_publish = task.publish
original_run = task.run


def publish():
    sha = original_publish()
    task.git('checkout', '--detach', sha)
    return sha


def run(name, command, **kwargs):
    # Prettier first, then the repository's blank-line/import rules. The
    # formatter and ESLint otherwise undo each other's statement spacing.
    if name == 'lint':
        original_run('eslint-final-fix', ['npx', 'eslint', '--fix', *command[2:]], **kwargs)
    return original_run(name, command, **kwargs)


task.publish = publish
task.run = run
sys.exit(task.main())
