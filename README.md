# Internal Sysand Project Index Example -- GitHub edition

An example GitHub repository and GitHub workflow that could be used to self-host
an internal (private) SysML v2 Project Index for use with
[Sysand](https://github.com/sensmetry/sysand).

This example is not intended to be the one and only approach for self-hosting a
project index, but rather a way to quickly spin up an initial index. The
included GitHub workflow is also very minimal and the end-users should customise
it for their needs (e.g. adding quality gates).

> [!NOTE]
> Since GitHub Pages do not allow authorization using Personal Access
> Tokens, this example is a workaround that uses
> `raw.githubusercontent.com` to expose the files to Sysand CLI.
> Sensmetry cannot guarantee that accessing files through
> `raw.githubusercontent.com` will not be rate-limited by GitHub, thus if you
> expect a large volume of requests going to this index, this solution might
> not be ideal.

The URL of the index will look something like this:
`https://raw.githubusercontent.com/OWNER/REPO/refs/heads/main/`

## How this works

The index are just files in a GitHub repository. GitHub is just used to host
the files with authentication.

## Deployment workflow

1. Go to index directory (`cd index`) - this is the package index root.
2. Add a `.kpar` to the index by following [Add Project to Index](https://docs.sysand.org/hosting_index.html#add-project-to-the-index).
3. Commit and push the changes to the `main` branch.

## Using workflow

1. Create a [GitHub Personal Access
   Token](https://github.com/settings/personal-access-tokens) (we recommend
   using fine-grained tokens) scoped to the index repository and the `Contents`
   read-only permissions.
2. Create a `.env` file or use other means to set the following environment
   variables. For `<X>` you can use whatever you want.
    - `SYSAND_CRED_<X>` with the value
      `https://raw.githubusercontent.com/OWNER/REPO/refs/heads/main/**` (the
      `refs/heads/main/**` part is important!)
    - `SYSAND_CRED_<X>_BEARER_TOKEN` with the value set to the Personal Access
      Token generated in step 1.
    - For more information about how Sysand deals with Authentication, refer to
      [Sysand documentation](https://docs.sysand.org/authentication.html).
    - An example `.env.example` file is provided in this repo.
3. Use the `--index` Sysand CLI argument with the value of
   `https://raw.githubusercontent.com/OWNER/REPO/refs/heads/main/` when
   installing the packages from this index OR use `sysand.toml` config file with
   the index set there.
    - For more information about how to set up Sysand to use custom indices,
      refer to [Sysand
      documentation](https://docs.sysand.org/config/indexes.html).
    - An example `sysand.toml` config file is provided in this repo.

## First time setup

You need to set up a GitHub repo as follows:

- Commit anything to the `main` branch.
- Push the `main` branch to GitHub.

Don't forget to update the `OWNER/REPO` parts of the `raw.githubusercontent.com`
URLs in this `README.md`, [`.env.example`](.env.example), and
[`sysand.toml`](sysand.toml) files, to make it easier for your colleagues to
access the index URL.
