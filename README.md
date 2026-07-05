# Private sysand index (GitHub)

Welcome! This repository is your team's private package index for
SysML v2 / KerML projects, used with the
[sysand](https://docs.sysand.com/client/) tool. If someone pointed you
here, this is where your team's shared models live: you can **install**
them into your own projects, and **publish** new versions for others to
use. You don't need to understand how the repository works internally —
find the section below that matches what you want to do, and follow it
step by step.

- [I want to use a project from this index](#install-a-project)
- [I want to publish a project to this index](#publish-a-project)
- I administer this index (or want to set up one like it) →
  [ADMINISTRATION.md](ADMINISTRATION.md)

## Install a project

You need two things from whoever administers this index: the **index URL**
and a **read token**. Then tell `sysand` about them (replace the
placeholders):

```sh
export SYSAND_CRED_TEAMIDX="<index URL>**"
export SYSAND_CRED_TEAMIDX_BEARER_TOKEN="<read token>"
sysand add pkg:sysand/<publisher>/<project> --index "<index URL>"
```

That's it — `sysand` downloads the project and its dependencies like from
any other index. To avoid retyping, the URL and credentials can be stored
in `sysand.toml`; see the
[sysand documentation](https://docs.sysand.com/client/).

## Publish a project

Publishing is done by adding your project's `.kpar` file (produced by
`sysand build`) to this repository through a pull request. The automation
takes care of everything else.

1. Clone this repository and create a branch for your submission:

   ```sh
   git clone git@github.com:YOUR-ORG/YOUR-INDEX.git && cd YOUR-INDEX
   git switch -c submit/my-project-1.0.0
   ```

2. Copy your `.kpar` file — exactly as `sysand build` produced it, no
   renaming — into the `kpars/` folder:

   ```sh
   cp path/to/my_project-1.0.0.kpar kpars/
   ```

   Everything about your project (publisher, name, version) is read from
   the file itself.

3. Commit, push, and open a pull request:

   ```sh
   git add kpars && git commit -m "submit: my-team/my-project 1.0.0"
   git push -u origin HEAD
   ```

A validation check runs on your pull request and posts a comment showing
exactly what your file contains — project, version, license, model files,
dependencies — so your reviewers know what they are approving. Once
approved and merged, automation publishes your project; it is installable
about a minute later.

One thing to know: a version, once published, is permanent — to change
something, publish a new version.

Publishing can also be automated from your project's own repository (for
example on every release tag) — the release job performs the same steps,
or opens the pull request with `gh pr create`.
