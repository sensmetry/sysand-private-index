# Private sysand index (GitHub)

This repository hosts a private [sysand](https://docs.sysand.com/client/)
index for a team on GitHub. Team members publish SysML v2 / KerML projects
by pull request; automation validates each submission and maintains the
index files; consumers install with the `sysand` client.

To run your own: copy this repository (keeping both branches) and follow
the setup below.

## How it works

| Branch | Contents | Who writes it |
| ------ | -------- | ------------- |
| `main` | the index (`index/`), `publishers.toml`, automation | the writer workflow only |
| `staging` | `inbox/` — submissions awaiting processing | contributors, via pull request |

Publishing a project means getting its `.kpar` file into
`inbox/<publisher>/<name>/<version>/project.kpar` on `staging`. Every push
to `staging` runs the **writer** (`.github/workflows/writer.yml`), which
checks the submission against `publishers.toml`, adds it to the index on
`main` with `sysand index add`, and clears the inbox. Nobody edits `index/`
by hand.

```
README.md                   this file
publishers.toml             who may publish what (edit this)
index/                      the index consumers read (managed by automation)
inbox/                      (staging branch) submission drop-off
scripts/index_ci.py         validation + writer logic (Python >= 3.11, stdlib only)
.github/workflows/          writer + pull-request validation
.github/CODEOWNERS          who reviews which publisher's submissions (edit this)
```

## Setup

1. Copy this repository into your organization as a **private** repo, with
   both `main` and `staging`.
2. Create a fine-grained personal access token of a machine account (or a
   GitHub App token) with **Contents: read and write** on this repo. Save
   it as an Actions secret named `INDEX_WRITER_TOKEN`.
3. Protect `main`: no direct pushes, no pull requests; allow only the
   token's identity (branch protection bypass list). Without the secret,
   the writer falls back to the workflow's own token, which only works
   while `main` is unprotected — fine for trying things out, not for real
   use.
4. Protect `staging`: require pull requests with review and **Require
   review from Code Owners**.
5. Declare each publisher in `publishers.toml` and give it an owning team
   in `.github/CODEOWNERS` (see the comments in both files).

## Publish a project

Build a KPAR (`sysand build`), then:

```sh
git clone -b staging git@github.com:YOUR-ORG/YOUR-INDEX.git && cd YOUR-INDEX
git switch -c submit/my-project-1.0.0
mkdir -p inbox/my-team/my-project/1.0.0
cp path/to/my_project-1.0.0.kpar inbox/my-team/my-project/1.0.0/project.kpar
git add inbox && git commit -m "submit: my-team/my-project 1.0.0"
git push -u origin HEAD    # then open a PR targeting staging
```

The path must match the KPAR: `<publisher>` and `<name>` become the
project's identifier `pkg:sysand/<publisher>/<name>`, and `<version>` must
equal the version in the KPAR's metadata — mismatches are rejected. After
the code owners merge, the project is installable within about a minute.

To publish from another repository's CI (e.g. on every release tag), have
that job perform the same steps with a token, or open the PR with
`gh pr create`.

**Never republish different bytes under an existing version** — consumers
verify digests recorded at publish time. Release a new version instead. To
retire a version, a maintainer runs
`sysand index yank <iri> --version <v> --index-root index` on a branch of
`main` and merges it (yanked versions stay downloadable for existing
lockfiles but are not picked for new ones).

## Install from the index

Readers need a **classic** personal access token with read access to this
repo (a shared machine-account token works well; fine-grained tokens are
unreliable against `raw.githubusercontent.com`):

```sh
export SYSAND_CRED_TEAMIDX="https://raw.githubusercontent.com/YOUR-ORG/YOUR-INDEX/refs/heads/main/index/**"
export SYSAND_CRED_TEAMIDX_BEARER_TOKEN="ghp_..."
sysand add pkg:sysand/my-team/my-project \
  --index https://raw.githubusercontent.com/YOUR-ORG/YOUR-INDEX/refs/heads/main/index/
```

See the [sysand documentation](https://docs.sysand.com/client/) for
credential and index configuration in `sysand.toml`. Note that
`raw.githubusercontent.com` content can lag pushes by a few minutes and has
unpublished rate limits; it works well at team scale.

## Maintenance

- **After changing `scripts/` or `.github/` on `main`, merge `main` into
  `staging`.** The writer runs from the staging branch, so a stale staging
  runs old automation — the most common cause of writer failures.
- The writer processes the whole inbox as one batch; a bad entry blocks the
  batch until removed (check the failed workflow run's log).
- Submitted KPAR files stay in `staging`'s git history after processing.
  If the repository grows, recreate `staging` from `main` (plus
  `inbox/README.md`).
- `sysand-index-config.json.example` is not used today; its comment
  explains when it becomes relevant.
