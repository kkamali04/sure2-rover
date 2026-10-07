# Local Git upload checks

Activate after cloning:

```sh
git config core.hooksPath .githooks
git config pull.ff only
git config pull.rebase false
```

Python 3 and Git must be available. The hooks stop a commit containing newly
staged files above 100,000,000 bytes (100 MB), and stop a push containing oversized blobs anywhere
in its outgoing history. Existing remote history is excluded from that check.
Small report/demo files remain supported. Intentional large files need a
separate storage decision, such as Git LFS, before committing.

Pull with `git pull --ff-only` before making changes. Do not create merge
commits to reconcile divergence. Finish and check the work, then push at the
end. These pull settings are active in this checkout. Preserve complete content
when making smaller copies; do not truncate artifacts just to meet the limit.

The hooks are enabled in this checkout. Git does not automatically activate
tracked hooks on another clone. Downloaded ENEB454 TA demo videos and Python
caches are ignored within that class folder; they remain available locally.

On September 21, 2026, the rejected local commit 622fc3f2 was saved under
`refs/backup/large-file-fix-622fc3f2` before amendment. This local recovery ref
retains the original commit without including it in an ordinary branch push.
