#!/usr/bin/env python3
"""CI logic for this private sysand index.

Subcommands:
  reconcile         The index-writer: publish every kpars/ file not yet in
                    the generated index branch. Idempotent - already-published
                    files (by digest) are skipped; nothing is ever removed.
  validate BASEREF  Pre-merge validation for MRs/PRs: for each submitted
                    KPAR, dry-runs the actual publish against a throwaway
                    checkout of the index branch (nothing is pushed), prints
                    one result line per submission, and exits non-zero if any
                    submission is rejected.

A submission is a KPAR file exactly as `sysand build` produced it, placed
directly in kpars/ on the default branch, where it remains: the folder is
the declarative set of submitted artifacts, and the index-writer reconciles
the index branch against it. The project's identity - publisher, name,
version - comes from the KPAR's own metadata. Review of the pull/merge
request is the publishing gate: what reviewers approve gets published.

Invariants:
- The index-writer runs serialized (GitHub `concurrency:` / GitLab
  `resource_group`) and is the only writer of the index branch, so its push
  never races.
- Prior index state is read from git, never from a deployed/served copy.
- Published versions are immutable: the index-writer only ever adds, and a
  changed KPAR under an already-published version is an error.

Requires: Python >= 3.11, git, sysand on PATH.
Expects: cwd = repo root, checkout of the source branch tip, push
credentials configured on the remote.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REMOTE = "origin"
INDEX_BRANCH = "index"
GIT_USER = "index-writer"
GIT_EMAIL = "index-writer@example.invalid"

KPARS = Path("kpars")
WORKTREE = Path(".index-work")
ENTRY_RE = re.compile(r"^kpars/[^/]+\.kpar$")
# Files under kpars/ that are not submissions but are allowed to exist.
KPARS_ALLOWED = {Path("kpars/README.md")}


class Fail(Exception):
    """Validation or publish failure with a user-facing message."""


def run(*args, cwd=None, check=True, quiet=False):
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if quiet else None,
        stderr=subprocess.STDOUT if quiet else None,
    )


def git(*args, cwd=None, check=True, quiet=False):
    return run("git", *args, cwd=cwd, check=check, quiet=quiet)


def git_out(*args, cwd=None):
    return subprocess.run(
        ("git", *args), cwd=cwd, check=True, text=True, capture_output=True
    ).stdout


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def kpar_label(path):
    """Short identity of a KPAR, from its own metadata: `pub/name X.Y.Z`."""
    try:
        with zipfile.ZipFile(path) as zf:
            project = json.loads(zf.read(".project.json"))
    except Exception as exc:
        raise Fail(f"not a readable KPAR ({exc})") from exc
    lic = project.get("license")
    suffix = f" (license {lic})" if lic else ""
    return f"{project.get('publisher')}/{project.get('name')} {project.get('version')}{suffix}"


def find_entries():
    entries = []
    for path in sorted(KPARS.rglob("*")):
        if path.is_dir() or path in KPARS_ALLOWED:
            continue
        if not ENTRY_RE.match(path.as_posix()):
            raise Fail(f"{path}: submissions must be .kpar files directly in kpars/")
        entries.append(path)
    return entries


def published_digests():
    """sha256 of every KPAR already on the index branch (in the worktree)."""
    return {sha256(p) for p in WORKTREE.glob("*/*/*/project.kpar")}


def remove_worktree():
    git("worktree", "remove", "--force", str(WORKTREE), check=False, quiet=True)
    git("worktree", "prune", quiet=True)


def add_entry(entry):
    """Add one KPAR to the index worktree; sysand derives and validates the
    project's identity from the KPAR metadata. Stage the result."""
    result = run("sysand", "index", "add", "--kpar-path", str(entry),
                 "--index-root", str(WORKTREE), check=False, quiet=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        if "already exists" in (result.stdout or ""):
            raise Fail(
                "this version is already published with different content - "
                "published versions are immutable; bump the version"
            )
        reason = next(
            (l for l in (result.stdout or "").splitlines() if l.startswith("error")),
            "sysand index add failed",
        )
        raise Fail(reason)
    if not git_out("status", "--porcelain", cwd=WORKTREE).strip():
        raise Fail("sysand index add changed nothing")
    git("add", "-A", cwd=WORKTREE, quiet=True)


def publish_batch(entries):
    """Publish every not-yet-published entry to the index branch. The
    index-writer is serialized and the sole writer of that branch, so the
    push does not race; a failed push means re-run the job."""
    git("fetch", REMOTE, INDEX_BRANCH, quiet=True)
    remove_worktree()
    git("worktree", "add", "--detach", str(WORKTREE), f"{REMOTE}/{INDEX_BRANCH}", quiet=True)
    try:
        published = published_digests()
        new = [e for e in entries if sha256(e) not in published]
        if not new:
            print("Everything in kpars/ is already published - nothing to do.")
            return
        print(f"Publishing {len(new)} artifact(s):")
        for entry in new:
            print(f"  {entry}")
            add_entry(entry)
        git(
            "-c", f"user.name={GIT_USER}", "-c", f"user.email={GIT_EMAIL}",
            "commit", "-m", "index: publish " + " ".join(e.name for e in new),
            cwd=WORKTREE, quiet=True,
        )
        push = git("push", REMOTE, f"HEAD:refs/heads/{INDEX_BRANCH}", cwd=WORKTREE, check=False)
        if push.returncode != 0:
            raise Fail(f"push to {INDEX_BRANCH} failed - re-run the index-writer to retry")
    finally:
        remove_worktree()


def cmd_reconcile():
    run("sysand", "--version", quiet=True)  # fail fast if missing
    if git("fetch", REMOTE, INDEX_BRANCH, check=False, quiet=True).returncode != 0:
        raise Fail(
            f"branch '{INDEX_BRANCH}' does not exist on {REMOTE} - it holds "
            "the generated index and must be created once (see ADMINISTRATION.md)"
        )
    entries = find_entries()
    if not entries:
        print("kpars/ is empty - nothing to do.")
        return 0
    publish_batch(entries)
    return 0


def cmd_validate(base_ref):
    """Validate the diff BASE_REF...HEAD: dry-run the publish of each
    submitted KPAR against a throwaway index-branch worktree, print one
    result line per submission, and exit non-zero if any is rejected."""
    changed = []
    for line in git_out(
        "diff", "--name-status", "--diff-filter=ACMR", f"{base_ref}...HEAD"
    ).splitlines():
        status, _, rest = line.partition("\t")
        path = rest.split("\t")[-1]  # renames/copies: take the new path
        changed.append((status[0], path))
    if not changed:
        print("No changes.")
        return 0

    # Dry-run target: the real index branch in a throwaway worktree.
    dry_run = False
    published = set()
    if any(ENTRY_RE.match(p) and s != "M" for s, p in changed):
        if git("fetch", REMOTE, INDEX_BRANCH, check=False, quiet=True).returncode == 0:
            remove_worktree()
            git("worktree", "add", "--detach", str(WORKTREE), f"{REMOTE}/{INDEX_BRANCH}", quiet=True)
            published = published_digests()
            dry_run = True
        else:
            print(f"note: no '{INDEX_BRANCH}' branch on {REMOTE} - skipping publish dry-run")

    failures = 0
    try:
        for status, path in changed:
            if ENTRY_RE.match(path) and status == "M":
                print(f"FAIL  {path}: published artifacts are immutable - publish a new version")
                failures += 1
            elif ENTRY_RE.match(path):
                try:
                    label = kpar_label(Path(path))
                except Fail as exc:
                    print(f"FAIL  {path}: {exc}")
                    failures += 1
                    continue
                if not dry_run:
                    print(f"ok    {path}: {label} - not checked (no index branch yet)")
                elif sha256(Path(path)) in published:
                    print(f"ok    {path}: {label} - already published, index-writer will skip")
                else:
                    try:
                        add_entry(Path(path))
                        print(f"ok    {path}: {label} - dry-run ok, publishes on merge")
                    except Fail as exc:
                        print(f"FAIL  {path}: {exc}")
                        failures += 1
            elif Path(path) in KPARS_ALLOWED:
                pass  # ordinary docs change under kpars/
            elif path.startswith("kpars/"):
                print(f"FAIL  {path}: submissions must be .kpar files directly in kpars/")
                failures += 1
            # other files are ordinary code/docs changes, reviewed as such
    finally:
        if dry_run:
            remove_worktree()
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reconcile", help="run the index-writer (kpars/ -> index branch)")
    validate = sub.add_parser("validate", help="validate a submission diff")
    validate.add_argument("base_ref", help="merge base, e.g. origin/main")
    args = parser.parse_args()
    try:
        if args.command == "reconcile":
            return cmd_reconcile()
        return cmd_validate(args.base_ref)
    except Fail as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        cmd = " ".join(map(str, exc.cmd))
        if exc.stdout:
            print(exc.stdout, file=sys.stderr)
        print(f"ERROR: command failed ({exc.returncode}): {cmd}", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    sys.exit(main())
