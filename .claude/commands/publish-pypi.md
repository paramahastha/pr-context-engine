---
description: Publish a new release to PyPI — bumps version, updates CHANGELOG, commits, tags, and merges to main. Usage: /publish-pypi [patch|minor|major] (default: patch)
---

Publish a new version of pr-context-engine to PyPI using the project's GitHub Actions release flow.

**Bump type**: $ARGUMENTS (default to `patch` if empty)

Follow these steps exactly, in order:

## 1. Read current version
Read `pyproject.toml` and extract the current `version` field.

## 2. Compute new version
Apply the bump type to the current version (semver):
- `patch` — increment the third number (0.1.2 → 0.1.3)
- `minor` — increment the second number, reset patch (0.1.2 → 0.2.0)
- `major` — increment the first number, reset minor and patch (0.1.2 → 1.0.0)

## 3. Update pyproject.toml
Edit the `version` field in `pyproject.toml` to the new version.

## 4. Update CHANGELOG.md
Read `CHANGELOG.md`. Under `## Unreleased`, look at what's there.
- If `## Unreleased` has content, move it into a new dated section `## X.Y.Z — YYYY-MM-DD` (use today's date) inserted below `## Unreleased`.
- If `## Unreleased` is empty, create the new section anyway and populate it by summarising the commits since the last tag: run `git log $(git describe --tags --abbrev=0)..HEAD --oneline` to get them, then write a short changelog entry under `### Fixed`, `### Added`, or `### Changed` as appropriate.
- Leave `## Unreleased` as an empty section above the new version section.

## 5. Commit the version bump
Stage only `pyproject.toml` and `CHANGELOG.md`, then commit with message:
`chore: bump version to X.Y.Z`

Do NOT commit anything else.

## 6. Push the current branch
Run `git push origin <current-branch>`.

## 7. Tag and push the tag
```
git tag vX.Y.Z
git push origin vX.Y.Z
```
This triggers the `release.yml` GitHub Actions workflow, which builds and publishes to PyPI via OIDC trusted publishing — no credentials needed.

## 8. Merge to main
```
git checkout main
git merge <previous-branch> --ff-only
git push origin main
git checkout <previous-branch>
```

## 9. Confirm
Report:
- New version published: `X.Y.Z`
- Tag pushed: `vX.Y.Z`
- GitHub Actions release workflow URL: `https://github.com/paramahastha/pr-context-engine/actions`
- PyPI package URL: `https://pypi.org/project/pr-context-engine/X.Y.Z/`
