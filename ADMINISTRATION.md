# Administering this index

This page is for the person who runs the index — or wants to copy this
repository to run their own. For installing and publishing, see the
[README](README.md).

## How it works

| Branch | Contents | Who writes it |
| ------ | -------- | ------------- |
| `main` | the index (`index/`), `publishers.toml`, automation | the writer workflow only |
| `staging` | `inbox/` — submissions awaiting processing | contributors, via pull request |

Every push to `staging` runs the **writer**
(`.github/workflows/writer.yml`), which checks each inbox entry against
`publishers.toml`, adds it to the index on `main` with `sysand index add`,
and clears the inbox. Nobody edits `index/` by hand. The index is served
to `sysand` by `raw.githubusercontent.com` from `main`.

```
publishers.toml             who may publish what (edit this)
index/                      the index consumers read (managed by automation)
inbox/                      (staging branch) submission drop-off
scripts/index_ci.py         validation + writer logic (Python >= 3.11, stdlib only)
.github/workflows/          writer + pull-request validation
.github/CODEOWNERS          who reviews which publisher's submissions (edit this)
```

## Set up your own

1. Copy this repository into your organization as a **private** repo, with
   both `main` and `staging`.
2. Lock `main` with a ruleset (**Settings → Rules → Rulesets**): target
   `main`, enable **Restrict updates**, and add **GitHub Actions** to the
   ruleset's bypass list. Nobody — including admins — can then push to
   `main` except the writer workflow. (The GitHub Actions bypass actor is
   available in organization-owned repositories; on a personal repository,
   leave `main` unprotected while trying things out.)
3. Protect `staging`: require pull requests with review and **Require
   review from Code Owners**.
4. Declare each publisher in `publishers.toml` and give it an owning team
   in `.github/CODEOWNERS` (see the comments in both files).

## What to give consumers

- **Index URL**:
  `https://raw.githubusercontent.com/YOUR-ORG/YOUR-INDEX/refs/heads/main/index/`
- **Read token**: a **classic** personal access token with read access to
  this repository — typically from a shared machine account. (Fine-grained
  tokens are unreliable against `raw.githubusercontent.com`.)

Note that `raw.githubusercontent.com` content can lag pushes by a few
minutes and has unpublished rate limits; it works well at team scale.

## Maintenance

- **After changing `scripts/` or `.github/` on `main`, merge `main` into
  `staging`.** The writer runs from the staging branch, so a stale staging
  runs old automation — the most common cause of writer failures.
- The writer processes the whole inbox as one batch; a bad entry blocks
  the batch until removed (check the failed workflow run's log).
- To retire a published version, run
  `sysand index yank <iri> --version <v> --index-root index` on a branch
  of `main` and merge it through your ruleset's exception process (yanked
  versions stay available to existing lockfiles but are not picked for new
  ones). Never replace a published version's bytes — consumers verify
  digests recorded at publish time.
- Submitted `.kpar` files stay in `staging`'s git history after
  processing. If the repository grows, recreate `staging` from `main`
  (plus `inbox/README.md`).
- `sysand-index-config.json.example` is not used today; its comment
  explains when it becomes relevant.
