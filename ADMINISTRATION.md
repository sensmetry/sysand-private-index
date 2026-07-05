# Administering this index

This page is for the person who runs the index — or wants to copy this
repository to run their own. For installing and publishing, see the
[README](README.md).

## How it works

| Branch | Contents | Who writes it |
| ------ | -------- | ------------- |
| `main` | inbox, automation, docs — a normal default branch | contributors via pull request |
| `index` | the **generated index** consumers read (index files at the branch root) | the writer workflow only |

Submissions are KPAR files placed directly in `inbox/` via pull requests
to `main`; publisher, name, and version come from each KPAR's own
metadata. Every push to `main` runs the **writer**
(`.github/workflows/writer.yml`), which adds each inbox entry to the
`index` branch with `sysand index add` and then clears the inbox (a
`[skip ci]` commit on `main`). Nobody edits the `index` branch by hand,
and nothing needs to be kept in sync between branches — workflows and
scripts run from `main` like in any normal repository. The index is
served to `sysand` by `raw.githubusercontent.com` from the `index`
branch.

**Review is the publishing gate**: whatever reviewers approve on `main`
gets published. To make that review meaningful, the validation workflow
posts a report on each pull request describing every submitted KPAR
(project, version, license, contents, digest).

```
inbox/                      submission drop-off (cleared by the writer)
scripts/index_ci.py         validation + writer logic (Python >= 3.11, stdlib only)
.github/workflows/          writer + pull-request validation
```

## Set up your own

1. Copy this repository into your organization as a **private** repo, with
   both the `main` and `index` branches.
2. Protect `main`: require pull requests with at least one approving
   review. Whoever can approve pull requests can publish — that review is
   the entire authorization model, so choose the approvers accordingly.
   The writer must be able to push its inbox-cleanup commits directly: add
   **GitHub Actions** to the ruleset's bypass list (available in
   organization-owned repositories; on a personal repository, leave `main`
   unprotected while trying things out).
3. Protect `index` with a ruleset: **Restrict updates**, with **GitHub
   Actions** as the only bypass — the writer is then the only thing that
   can touch the published index.

If the `index` branch is ever missing (it holds only generated content),
recreate it: `git switch --orphan index`, run `sysand index init`, commit,
push.

## What to give consumers

- **Index URL**:
  `https://raw.githubusercontent.com/YOUR-ORG/YOUR-INDEX/refs/heads/index/`
- **Read token**: a **classic** personal access token with read access to
  this repository — typically from a shared machine account. (Fine-grained
  tokens are unreliable against `raw.githubusercontent.com`.)

Note that `raw.githubusercontent.com` content can lag pushes by a few
minutes and has unpublished rate limits; it works well at team scale.

## Maintenance

- The writer processes the whole inbox as one batch; a bad entry blocks
  the batch until removed (check the failed workflow run's log).
- To retire a published version, run
  `sysand index yank <iri> --version <v> --index-root .` on a checkout of
  the `index` branch and push it through your ruleset's exception process
  (yanked versions stay available to existing lockfiles but are not
  picked for new ones). Never replace a published version's bytes —
  consumers verify digests recorded at publish time.
- Submitted `.kpar` files remain in `main`'s git history after the inbox
  is cleared, so repository size grows with publish volume. Keep KPARs
  modest; if this becomes a problem, ask about index formats that store
  archives outside git.
- `sysand-index-config.json.example` is not used today; its comment
  explains when it becomes relevant.
