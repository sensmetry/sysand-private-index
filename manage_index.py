#!/usr/bin/env python3
"""Maintain this private sysand index from CI.

Two subcommands, both run by the repository's CI:

  reconcile      Publish every package in ``kpars/`` that is not yet in the
                 generated ``index`` branch, then stop. Idempotent: packages
                 already published (matched by content digest) are skipped and
                 nothing is ever removed.

  validate REF   Check a pull/merge request before it is merged. For each
                 submitted package, print one result line and dry-run the real
                 publish against a throwaway copy of the ``index`` branch
                 (nothing is pushed). Exit non-zero if any submission is
                 rejected, which fails the check.

A submission is a KPAR file, exactly as ``sysand build`` produced it, added to
``kpars/`` on the default branch. The file stays there: ``kpars/`` is the
record of what has been submitted. A package's identity (publisher, name,
version) comes from its own metadata, so no naming convention is imposed.

The ``index`` branch is generated and writer-only. ``reconcile`` reads the
current index from git (never from a served copy), adds new packages with
``sysand index add``, and pushes. CI serializes this script and it is the only
writer of the ``index`` branch, so its push never races; a failed push simply
means "run reconcile again".

Requires Python >= 3.12, git, and sysand on PATH. Run from the repository root
with push credentials configured on the remote.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from contextlib import contextmanager, nullcontext
from pathlib import Path

REMOTE = "origin"
INDEX_BRANCH = "index"
INDEX_WRITER = ("index-writer", "index-writer@example.invalid")  # git commit author

KPARS_DIR = Path("kpars")
WORKTREE = Path(".index-work")
# A submission is a .kpar directly in kpars/; kpars/README.md is documentation.
DOC_FILES = {KPARS_DIR / "README.md"}
SUBMISSION_RE = re.compile(rf"^{KPARS_DIR}/[^/]+\.kpar$")


class Rejected(Exception):
    """A submission (or the whole run) is invalid, with a reason to show."""


# --- running commands ------------------------------------------------------


def git(*args, cwd=None, check=True, quiet=False):
    """Run git. With ``quiet`` the output is captured instead of streamed,
    for plumbing whose output would only clutter the CI log."""
    return subprocess.run(
        ("git", *args), cwd=cwd, check=check, text=True, capture_output=quiet
    )


def git_stdout(*args, cwd=None):
    """Run git and return its stdout, for commands whose output we parse."""
    return git(*args, cwd=cwd, quiet=True).stdout


def require_sysand():
    """Fail early, with a clear message, if sysand is not available."""
    try:
        subprocess.run(("sysand", "--version"), check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Rejected("sysand is not available on PATH") from exc


# --- reading a package -----------------------------------------------------


def digest(path):
    """SHA-256 of a file: the content identity used to tell packages apart."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def kpar_summary(kpar):
    """One-line identity of a KPAR from its own metadata, e.g.
    ``acme/widgets 1.2.0 (license MIT)``. Raises Rejected if unreadable."""
    try:
        with zipfile.ZipFile(kpar) as archive:
            project = json.loads(archive.read(".project.json"))
    except Exception as exc:
        raise Rejected(f"not a readable KPAR ({exc})") from exc
    identity = (
        f"{project.get('publisher')}/{project.get('name')} {project.get('version')}"
    )
    license_name = project.get("license")
    return f"{identity} (license {license_name})" if license_name else identity


# --- the index branch worktree ---------------------------------------------


def _prune_worktree():
    git("worktree", "remove", "--force", str(WORKTREE), check=False, quiet=True)
    git("worktree", "prune", quiet=True)


def index_branch_exists():
    """Whether the remote has the index branch (this also fetches it)."""
    return git("fetch", REMOTE, INDEX_BRANCH, check=False, quiet=True).returncode == 0


@contextmanager
def index_worktree():
    """Check the current index branch out into a throwaway worktree, and
    always clean it up. The caller reads and stages WORKTREE in place.
    The branch must already be fetched (see ``index_branch_exists``)."""
    _prune_worktree()
    git(
        "worktree",
        "add",
        "--detach",
        str(WORKTREE),
        f"{REMOTE}/{INDEX_BRANCH}",
        quiet=True,
    )
    try:
        yield
    finally:
        _prune_worktree()


def published_digests():
    """Digests of every already-published KPAR, read from the versions.json
    files in the checked-out index worktree. sysand records each KPAR's
    sha256 there, so we use that instead of re-hashing every archive."""
    digests = set()
    for versions_file in WORKTREE.glob("*/*/versions.json"):
        listing = json.loads(versions_file.read_text())
        for entry in listing.get("versions", []):
            recorded = entry.get("kpar_digest", "")
            if recorded.startswith("sha256:"):
                digests.add(recorded.removeprefix("sha256:"))
    return digests


def add_to_index(kpar):
    """Add one KPAR to the index worktree with ``sysand index add``, which
    derives and validates the package identity from the KPAR's own metadata,
    and stage the result. Raises Rejected with sysand's reason on failure."""
    result = subprocess.run(
        (
            "sysand",
            "index",
            "add",
            "--kpar-path",
            str(kpar),
            "--index-root",
            str(WORKTREE),
        ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(result.stdout, end="")  # surface sysand's own message in the log
    if result.returncode != 0:
        if "already exists" in result.stdout:
            raise Rejected(
                "this version is already published with different content; "
                "published versions are immutable, so bump the version"
            )
        error_line = next(
            (line for line in result.stdout.splitlines() if line.startswith("error")),
            "sysand index add failed",
        )
        raise Rejected(error_line)
    git("add", "-A", cwd=WORKTREE, quiet=True)


# --- reconcile: publish new submissions ------------------------------------


def submitted_kpars():
    """Every submission in ``kpars/``, or raise Rejected on a stray file."""
    kpars = []
    for path in sorted(KPARS_DIR.rglob("*")):
        if path.is_dir() or path in DOC_FILES:
            continue
        if path.parent != KPARS_DIR or path.suffix != ".kpar":
            raise Rejected(
                f"{path}: submissions must be .kpar files directly in kpars/"
            )
        kpars.append(path)
    return kpars


def reconcile():
    require_sysand()
    if not index_branch_exists():
        raise Rejected(
            f"the '{INDEX_BRANCH}' branch does not exist on {REMOTE}; it holds the "
            "generated index and must be created once (see ADMINISTRATION.md)"
        )
    kpars = submitted_kpars()
    if not kpars:
        print("kpars/ is empty - nothing to do.")
        return

    with index_worktree():
        already_published = published_digests()
        new = [kpar for kpar in kpars if digest(kpar) not in already_published]
        if not new:
            print("Every submission is already published - nothing to do.")
            return

        print(f"Publishing {len(new)} package(s):")
        for kpar in new:
            print(f"  {kpar}")
            add_to_index(kpar)

        name, email = INDEX_WRITER
        message = "index: publish " + " ".join(kpar.name for kpar in new)
        git(
            "-c",
            f"user.name={name}",
            "-c",
            f"user.email={email}",
            "commit",
            "-m",
            message,
            cwd=WORKTREE,
            quiet=True,
        )
        pushed = git(
            "push", REMOTE, f"HEAD:refs/heads/{INDEX_BRANCH}", cwd=WORKTREE, check=False
        )
        if pushed.returncode != 0:
            raise Rejected(
                f"pushing the {INDEX_BRANCH} branch failed - run reconcile again"
            )


# --- validate: check a pull/merge request ----------------------------------


def changed_files(base_ref):
    """(status letter, path) for each file added/copied/modified/renamed
    between ``base_ref`` and HEAD."""
    diff = git_stdout(
        "diff", "--name-status", "--diff-filter=ACMR", f"{base_ref}...HEAD"
    )
    changes = []
    for line in diff.splitlines():
        status, _, rest = line.partition("\t")
        changes.append((status[0], rest.split("\t")[-1]))  # for renames, the new path
    return changes


def check_submission(status, kpar, published):
    """Judge one submitted .kpar and return (ok, message). ``published`` is the
    set of digests already in the index, or None when there is no index branch
    to dry-run against."""
    if status == "M":
        return False, "published packages are immutable - publish a new version instead"
    try:
        summary = kpar_summary(kpar)
    except Rejected as exc:
        return False, str(exc)
    if published is None:
        return True, f"{summary} - not checked (no index branch yet)"
    if digest(kpar) in published:
        return True, f"{summary} - already published, will be skipped"
    try:
        add_to_index(kpar)  # the real publish, against the throwaway worktree
    except Rejected as exc:
        return False, f"{summary} - {exc}"
    return True, f"{summary} - publishes on merge"


def check_change(status, path, published):
    """Judge one changed file. Returns (ok, message) to report, or None if the
    file is not a submission and needs no comment."""
    if SUBMISSION_RE.match(path):
        return check_submission(status, Path(path), published)
    if Path(path) in DOC_FILES:
        return None  # documentation under kpars/
    if path.startswith(f"{KPARS_DIR}/"):
        return False, "submissions must be .kpar files directly in kpars/"
    return None  # ordinary code or docs change, reviewed on its own


def validate(base_ref):
    changes = changed_files(base_ref)
    if not changes:
        print("No changes to validate.")
        return 0

    has_submissions = any(SUBMISSION_RE.match(p) and s != "M" for s, p in changes)
    dry_run = has_submissions and index_branch_exists()
    if has_submissions and not dry_run:
        print(
            f"note: no '{INDEX_BRANCH}' branch on {REMOTE} yet - skipping the publish dry-run"
        )
    if dry_run:
        require_sysand()

    rejected = 0
    with index_worktree() if dry_run else nullcontext():
        published = published_digests() if dry_run else None
        for status, path in changes:
            result = check_change(status, path, published)
            if result is None:
                continue
            ok, message = result
            print(f"{'ok' if ok else 'FAIL':<4}  {path}: {message}")
            rejected += not ok
    return 1 if rejected else 0


# --- entry point -----------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reconcile", help="publish new submissions to the index branch")
    check = commands.add_parser(
        "validate", help="check a pull/merge request's submissions"
    )
    check.add_argument(
        "base_ref", metavar="REF", help="the target branch, e.g. origin/main"
    )
    args = parser.parse_args()

    try:
        if args.command == "reconcile":
            reconcile()
            return 0
        return validate(args.base_ref)
    except Rejected as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, file=sys.stderr)
        print(
            f"ERROR: {' '.join(map(str, exc.cmd))} exited {exc.returncode}",
            file=sys.stderr,
        )
        return exc.returncode or 1


if __name__ == "__main__":
    sys.exit(main())
