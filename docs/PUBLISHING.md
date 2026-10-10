# Publish rehearsal-kit to PyPI

`.github/workflows/publish.yml` builds, tests, and publishes the package when a GitHub Release is published. Ordinary pushes do not publish. A manual Actions run builds and checks the distributions without publishing.

## One-time account setup

1. Sign in to PyPI. For a new project, open [account publishing settings](https://pypi.org/manage/account/publishing/) and add a pending GitHub publisher. For an existing project you own, open its **Manage → Publishing** page instead.
2. Enter these exact values:

   | Field | Value |
   | --- | --- |
   | PyPI project name | `rehearsal-kit` |
   | GitHub owner | `MitudruDutta` |
   | Repository | `rehearsal` |
   | Workflow filename | `publish.yml` |
   | Environment | `pypi` |

3. In the GitHub repository's **Settings → Environments**, create `pypi` to match the publisher configuration. If release approval is configured there, approve the publishing job when ready.

Trusted Publishing uses GitHub's OIDC identity; no PyPI API token is required in repository secrets. A pending publisher creates the project on its first successful upload; it does not reserve the name beforehand. See [PyPI's setup guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) and [publishing guide](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## Each release

1. Set an unused version in `pyproject.toml` and keep `rehearsal/__init__.py` consistent.
2. Commit and push the intended release changes when authorized. Include the new workflow, its verification script, migrations, and console/font source files. Generated `dist/` and console export files stay ignored: Actions rebuilds them.
3. Create and publish a GitHub Release targeting that commit, with a tag matching the version exactly: `v0.1.0` for the current package version.
4. Watch **Actions → Build and publish Python package**. Its build job runs isolated unit tests, builds the console, creates wheel/source archives, checks metadata/resources, and verifies client installation. Only then can the separate `pypi` job upload the verified artifacts.

The workflow has not been executed on GitHub yet. No release, commit, push, account configuration, or upload was performed as part of preparing these files.
