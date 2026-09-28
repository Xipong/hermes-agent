"""Resolve generator-owned style conflicts without discarding current main declarations."""
import pr120894_nonstream as a

resolve_source_conflicts = a.resolve_rebase


def resolve_rebase():
    paths = a.run("git", "diff", "--name-only", "--diff-filter=U", cwd=a.CANDIDATE).stdout.splitlines()
    if not paths:
        return resolve_source_conflicts()
    generated = {"apps/shared/src/gateway-contract.generated.ts", "apps/shared/src/gateway-contract.openrpc.json"}
    for path in paths:
        if path in generated:
            # An old formatting commit conflicted with main's new hermes_not_connected state.
            # The Python declarations are authoritative; verify() regenerates both artifacts.
            a.run("git", "diff", "--cc", "--", path, cwd=a.CANDIDATE,
                  log="generated-conflict-" + path.rsplit("/", 1)[-1] + ".diff")
            a.run("git", "checkout", "--ours", "--", path, cwd=a.CANDIDATE)
            a.run("git", "add", path, cwd=a.CANDIDATE)
    if set(paths) - generated:
        resolve_source_conflicts()


if __name__ == "__main__":
    a.resolve_rebase = resolve_rebase
    a.prepare()
    a.verify()
    a.publish()
