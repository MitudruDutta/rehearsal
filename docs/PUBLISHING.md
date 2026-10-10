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

1. Raise `version` in `pyproject.toml` (PEP 440, normalized, higher than every version on PyPI) and set the same version in `agent-plugin/plugin.json`, then run `python scripts/build_agent_plugin.py`.
2. Add a `## <version>` section to `CHANGELOG.md` that says what changed.
3. Merge to `main` through a pull request. The **Tests** workflow must pass: unit tests, integration tests against PostgreSQL, the console type check and build, and the agent plugin drift check.
4. Create and publish a GitHub Release from `main` with the tag `v<version>`, for example `v0.1.1`.
5. **Build and publish Python package** then runs these gates in order, and uploads only if all of them pass:

   | Gate | Refuses the release when |
   |---|---|
   | Tests (the same workflow as pull requests) | any unit or integration test, the console build, or the plugin drift check fails |
   | Version | the tag is not `v<version>`; the version is invalid, not normalized, already on PyPI, or not higher than PyPI's newest; `CHANGELOG.md` has no section for it; the agent plugin has another version; the release commit is not on `main` |
   | Build | the console or distributions do not build; strict metadata checks fail; an archive misses a migration, the console, the skill or another required file, or contains `.env`, `.git`, `node_modules` or `var` |
   | MCP server | the built wheel, installed with `[mcp]` in a clean environment, does not start over stdio, list all 18 tools, and ask for `rehearsal login` without a key |
   | Client install | the wheel or source archive does not install and run with client dependencies only on Python 3.11, 3.12, 3.13 and 3.14 |
   | Published | after upload, `pip install rehearsal-kit[mcp]==<version>` from PyPI does not report that version |

A manual run (**Actions → Build and publish Python package → Run workflow**) runs every gate and builds, reports version problems as warnings, and never uploads. Use it to rehearse a release before tagging.

Run the version gate locally before tagging:

```bash
GITHUB_EVENT_NAME=release RELEASE_TAG=v<version> python .github/scripts/check-release.py --version-only
```
