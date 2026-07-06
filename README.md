# Private Sysand index (GitHub)

This repository is your team's private package index for SysML v2 / KerML
projects, used with the [sysand](https://docs.sysand.com/client/) client.

## Contents

- [Browse projects](#browse-projects)
- [Install a project](#install-a-project)
- [Publish a project](#publish-a-project)
- Set up an index like this or administer it:
  [ADMINISTRATION.md](ADMINISTRATION.md)

## Browse projects

Projects live on this repository's
[**`index`** branch](https://github.com/YOUR-ORG/YOUR-INDEX/tree/index),
laid out as `<publisher>/<project>/` folders.

## Install a project

You need a **read token**:

1. Open [create a fine-grained token][token_template]. The link
   pre-fills everything except the repository selection: under
   **Repository access**, choose **Only select repositories** and pick
   **YOUR-ORG/YOUR-INDEX**.
2. Generate the token and copy it. GitHub shows it only once; the
   pre-filled expiration is 90 days, so create a new token when it
   expires.

Then, from inside the Sysand project that should use the dependency,
tell `sysand` about the index and the token (replace `<read token>` and
the project to install):

```sh
export SYSAND_CRED_TEAMIDX="https://raw.githubusercontent.com/YOUR-ORG/YOUR-INDEX/refs/heads/index/**"
export SYSAND_CRED_TEAMIDX_BEARER_TOKEN="<read token>"
sysand add <publisher>/<project> --index "https://raw.githubusercontent.com/YOUR-ORG/YOUR-INDEX/refs/heads/index/"
```

`sysand` downloads the project and its dependencies just like it would
from any other index. See
[Authenticate to an index](https://docs.sysand.com/client/how-to/authenticate-to-an-index/)
for how the `SYSAND_CRED_*` variables work, the Windows commands, and
why credentials stay in environment variables rather than configuration
files. To make this your default index so you can drop the `--index`
option, follow
[Configure a different default index](https://docs.sysand.com/client/how-to/configure-default-index/).

If you see `no resolver was able to resolve the IRI`, check three things:
(1) the token: GitHub reports bad auth as a 404, so a bad, expired, or
not-yet-approved token looks like a missing project (organizations can
require an admin to approve new tokens, and only members of **YOUR-ORG**
can create one; if you are an outside collaborator, ask your index
administrator); (2) that the `**` is still at the end of the
`SYSAND_CRED_*` URL; (3) the publisher/project spelling against the
`index` branch. A quick token check that does not change your project:

```sh
sysand info --iri pkg:sysand/<publisher>/<project> --index "https://raw.githubusercontent.com/YOUR-ORG/YOUR-INDEX/refs/heads/index/"
```

## Publish a project

You publish by adding your project's `.kpar` file (produced by
`sysand build`) to this repository through a pull request. The automation
handles the rest.

1. Clone this repository and create a branch for your submission:

   ```sh
   git clone git@github.com:YOUR-ORG/YOUR-INDEX.git && cd YOUR-INDEX
   git switch -c submit/my-project-1.0.0
   ```

2. Copy your `.kpar` file into the `kpars/` folder, exactly as
   `sysand build` produced it:

   ```sh
   cp path/to/my-project-1.0.0.kpar kpars/
   ```

3. Commit, push, and open a pull request:

   ```sh
   git add kpars && git commit -m "submit: my-team/my-project 1.0.0"
   git push -u origin HEAD
   ```

   If the push is rejected, ask your index administrator for write access.

A validation check on the pull request dry-runs the publish, so a bad
submission cannot be merged (a common rejection is a missing `publisher`
field in your project's `.project.json`). Once merged, the project is
installable a few minutes later.

One thing to know: a published version is permanent. To change something,
publish a new version.

[token_template]: https://github.com/settings/personal-access-tokens/new?name=YOUR-INDEX+read+token&description=Read+access+to+the+YOUR-ORG%2FYOUR-INDEX+Sysand+index&target_name=YOUR-ORG&contents=read&expires_in=90
