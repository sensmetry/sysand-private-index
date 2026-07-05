# Private sysand index — GitHub example

Example repository implementing the **short-term horizon** of the
[priv-index-plan](../priv-index-plan/README.md) goal specification on
GitHub: a private sysand index served by the forge, published to through a
staging-branch inbox and a single CI writer
([exploration 0011](../priv-index-plan/explorations/0011-staged-writer-pipeline.md)),
with the seams in place for the C1/C2 client epochs and the future OIDC
publish gateway.

## Layout and branches

| Branch | Contents | Who writes |
| ------ | -------- | ---------- |
| `main` | **index of record**: `index/` static tree (KPARs in-tree, current epoch), `publishers.toml`, scripts, workflows | the writer workflow only (protected) |
| `staging` | submission funnel: `inbox/<publisher>/<name>/<version>/project.kpar` | contributors via PR; CI bots via token push |

```
index/                      the sysand static index (index.json, <pub>/<name>/versions.json, ...)
inbox/                      (staging branch) submissions awaiting the writer
publishers.toml             publisher authorization, config-as-code
scripts/process-inbox.sh    the writer
scripts/validate-inbox.sh   PR fast-feedback validation
.github/workflows/writer.yml        writer trigger (push to staging, serialized)
.github/workflows/validate-pr.yml   PR validation
.github/CODEOWNERS          per-publisher review requirements on inbox paths
sysand-index-config.json.example    discovery-doc seam for the gateway epoch
```

## One-time setup

1. Create a **private** repo from this template; keep `main` and `staging`.
2. Protect `main`: no direct pushes, no PRs; allow only the writer's
   identity to push (fine-grained PAT of a machine account, or a GitHub App,
   listed in the branch-protection bypass/allow list).
3. Protect `staging`: require PRs + CODEOWNERS review (the MR-path
   submission gate). Optionally allow named bot accounts to push directly
   (the CI-token submission channel — see trade-off below).
4. Add the secret `INDEX_WRITER_TOKEN` (the token from step 2, with
   `contents: read/write` on this repo).
5. Declare publishers in `publishers.toml` and matching CODEOWNERS entries.

## Publishing (submission channels, priv-index-plan 0009)

**S1/S2 — PR to `staging`** (humans; works for CI too):

```sh
git switch staging && git pull
mkdir -p inbox/example-publisher/my-model/1.2.0
cp path/to/project.kpar inbox/example-publisher/my-model/1.2.0/
git switch -c submit/my-model-1.2.0
git add inbox && git commit -m "submit: example-publisher/my-model 1.2.0"
git push -u origin HEAD   # open PR targeting staging
```

On merge, the writer validates the KPAR against `publishers.toml` and the
path (`pkg:sysand/<publisher>/<name>`, declared version must match), runs
`sysand index add` against a fresh checkout of `main`, pushes with
rebase-retry, and clears the inbox entry.

**S4 — tag-is-publish from a model repo** (recommended producer UX): the
model repo's release workflow builds the KPAR and pushes the inbox entry to
`staging` with a fine-grained PAT (or opens the PR via `gh pr create`).
Keep this step thin — when the gateway ships it becomes `sysand publish`
and nothing else about the producer workflow changes.

**Interim trade-off**: direct bot pushes to `staging` gate on token
possession only; PR-only is stronger (review) but adds friction for CI.
Choose per publisher; the writer validates either way.

## Consuming (read side)

Reads bind to `raw.githubusercontent.com` in this epoch (see
priv-index-plan 0004 for the constraints — undocumented surface, opaque
rate limits, ~5 min CDN staleness, classic PAT only):

```sh
# machine account, classic PAT with repo read access
export SYSAND_CRED_IDX="https://raw.githubusercontent.com/OWNER/REPO/refs/heads/main/index/**"
export SYSAND_CRED_IDX_BEARER_TOKEN="ghp_..."
sysand sync   # with the index configured as:
# https://raw.githubusercontent.com/OWNER/REPO/refs/heads/main/index/
```

The client probes `<root>/sysand-index-config.json`, gets 404, and falls
back to using the root directly — correct for this epoch by construction.

## Upgrade seams (why this layout is future-proof)

- **C1 (header credentials)** → switch consumers to the **contents API**
  read surface (fine-grained read-only PATs, documented rate limits); the
  repo layout does not change.
- **C2 (download-URL indirection)** → KPAR bytes move from `index/` to
  **GitHub Releases** of this repo (≤2 GiB/asset); the writer's
  `index add` step gains an upload; inbox entries can become pointer
  manifests, eliminating KPAR blobs from git history.
- **Gateway** → deploy the gateway, copy `sysand-index-config.json.example`
  into `index/` with a real `api_root`, and add OIDC claim fields to
  `publishers.toml`. The gateway submits to `staging` like any other
  channel; the writer, `main`, and all consumers are untouched
  ([0011](../priv-index-plan/explorations/0011-staged-writer-pipeline.md)).

## Operational notes

- The writer is serialized (`concurrency: index-writer`) and reads prior
  state from git only — both are load-bearing (chart-releaser incidents,
  priv-index-plan 0008).
- The writer pushes with `INDEX_WRITER_TOKEN`, not `github.token`:
  `github.token` cannot bypass `main`'s protection, and its pushes trigger
  no downstream workflows (a trap if you later add a Pages/deploy step).
- KPAR blobs accumulate in `staging` history even after inbox cleanup;
  periodically reset `staging` onto `main`. Moot after C2.
- Yank: maintainer PR running `sysand index yank <iri> --version <v>`
  against `index/` — yanks are index-of-record edits, not submissions.
