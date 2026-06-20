# Releasing AgentBridge

This document is a checklist for maintainers when releasing a new version.

## Pre-Release

- [ ] All tests pass (`make test`)
- [ ] Live protocol tests pass (`make test-live`)
- [ ] Linting passes (`make lint`)
- [ ] Demo works (`make demo`)
- [ ] CHANGELOG.md is updated with the new version
- [ ] Version is bumped in `src/__init__.py` and `pyproject.toml`
- [ ] No breaking changes without proper deprecation warnings

## Release

1. **Create a release branch** (optional, for large releases):
   ```bash
   git checkout -b release/v0.1.1
   ```

2. **Bump version** in:
   - `src/__init__.py` (`__version__`)
   - `pyproject.toml` (`version`)

3. **Update CHANGELOG.md** — move items from `[Unreleased]` to the new version section

4. **Commit and tag**:
   ```bash
   git add -A
   git commit -m "Release v0.1.1"
   git tag v0.1.1
   git push origin main --tags
   ```

5. **Create GitHub Release**:
   - Go to https://github.com/shadowhunter-92/agentbridge/releases
   - Click "Draft a new release"
   - Choose the tag `v0.1.1`
   - Title: `AgentBridge 0.1.1`
   - Description: Copy from CHANGELOG.md
   - Click "Publish release"

6. **Automation triggers**:
   - `publish.yml` will auto-publish to PyPI
   - `docker-publish.yml` will build and push the Docker image

7. **Verify**:
   - Check PyPI: https://pypi.org/project/agentbridge/
   - Check Docker Hub: https://hub.docker.com/r/shadowhunter/agentbridge
   - Check that `pip install agentbridge==0.1.1` works

## Post-Release

- [ ] Announce on Twitter/X, LinkedIn, Reddit
- [ ] Update the "latest version" badge in README if needed
- [ ] Close any issues fixed in this release
- [ ] Monitor for bug reports in the first 24 hours

## Emergency Hotfix

If a critical bug is found after release:

1. Fix the bug on `main`
2. Run tests
3. Tag `v0.1.2` (bump patch version)
4. Push — automation handles the rest
