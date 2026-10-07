"""Reject Git blobs above the repository's strict 100 MB limit."""
import subprocess
import sys

LIMIT = 100_000_000
ZERO = "0" * 40


def git(*args, data=None):
    result = subprocess.run(["git", *args], input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def staged_objects():
    changed = set(git("diff", "--cached", "--name-only", "--no-renames",
                      "--diff-filter=AM", "-z").split(b"\0"))
    objects = {}
    for entry in git("ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, path = entry.split(b"\t", 1)
        mode, oid, stage = metadata.split()
        if path in changed and stage == b"0" and mode != b"160000":
            objects[oid.decode()] = path.decode("utf-8", "replace")
    return objects


def outgoing_objects(lines):
    objects = {}
    for line in lines:
        _, local_oid, _, remote_oid = line.split()
        if local_oid == ZERO:  # Deleting a remote ref sends no file contents.
            continue
        args = ["rev-list", "--objects", local_oid]
        if remote_oid == ZERO:
            args += ["--not", "--remotes"]
        else:
            args.append("^" + remote_oid)
        for entry in git(*args).decode("utf-8", "replace").splitlines():
            oid, _, path = entry.partition(" ")
            objects[oid] = path or oid
    return objects


def check(objects):
    if not objects:
        return 0
    data = ("\n".join(objects) + "\n").encode()
    entries = git("cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)",
                  data=data).decode().splitlines()
    oversized = []
    for entry in entries:
        oid, kind, size = entry.split()
        if kind == "blob" and int(size) > LIMIT:
            oversized.append((objects[oid], int(size)))
    if not oversized:
        return 0
    print("Blocked: Git contains files above the 100 MB repository limit.", file=sys.stderr)
    for path, size in oversized:
        print(f"  {size / 1_000_000:.2f} MB  {path}", file=sys.stderr)
    print("Keep downloads locally with .gitignore, or explicitly use Git LFS.\n"
          "For an already committed file, fix every affected unpushed commit;\n"
          "a later deletion alone does not remove it from outgoing history.", file=sys.stderr)
    return 1


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("staged", "push"):
        raise RuntimeError("Usage: check_large_files.py staged|push")
    objects = staged_objects() if sys.argv[1] == "staged" else outgoing_objects(sys.stdin)
    return check(objects)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"Large-file check failed: {exc}", file=sys.stderr)
        sys.exit(1)
