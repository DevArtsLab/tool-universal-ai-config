# Deployment Guide

This guide covers releasing and distributing the Universal AI Configuration
Manager.

Repository: `https://github.com/DevArtsLab/tool-universal-ai-config`
PyPI name: `universal-ai-config` (CLI command: `ai-config`)

## Distribution Channels

| Channel         | How users install                                                                                            | Status                    |
| --------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------- |
| PyPI            | `uv tool install universal-ai-config`, `pipx install universal-ai-config`, `pip install universal-ai-config` | Automated on tag          |
| GitHub Releases | Standalone binaries (`ai-config-<os>-<arch>`)                                                                | Automated on tag          |
| curl installer  | `curl -fsSL .../install.sh \| bash`                                                                          | Uses uv/pipx when present |
| Homebrew        | `brew install DevArtsLab/tap/ai-config`                                                                      | Manual (see below)        |

## One-Time Setup

### PyPI Trusted Publishing (recommended)

The publish workflow uses OIDC trusted publishing — no API tokens needed.

1. Go to https://pypi.org/manage/account/publishing/ (or create the project
   first via a pending publisher)
2. Add a publisher:
   - Owner: `DevArtsLab`
   - Repository: `tool-universal-ai-config`
   - Workflow: `publish.yml`
   - Environment: `pypi`
3. In the GitHub repo, create an environment named `pypi`
   (Settings → Environments → New environment)

Alternative: create a `PYPI_API_TOKEN` repo secret and pass it to the publish
step with `password: ${{ secrets.PYPI_API_TOKEN }}`.

## Release Process

Everything is driven by git tags:

```bash
# 1. Bump version in pyproject.toml
# 2. Commit and push to main
# 3. Tag and push
git tag v0.1.0
git push origin v0.1.0
```

Pushing a `v*` tag runs `.github/workflows/publish.yml`, which:

1. Verifies the tag matches `pyproject.toml` version
2. Builds sdist + wheel
3. Publishes to PyPI (trusted publishing)
4. Builds PyInstaller binaries (linux-x86_64, macos-x86_64, macos-arm64,
   windows-x86_64) and smoke-tests each
5. Creates a GitHub release with the binaries attached

The tag must match the `version` field in `pyproject.toml` or the workflow
fails.

## Manual PyPI Upload (fallback)

```bash
pip install build twine
python -m build
twine upload dist/*
```

## Homebrew Tap

Create `DevArtsLab/homebrew-tap` and add `Formula/ai-config.rb`:

```ruby
class AiConfig < Formula
  include Language::Python::Virtualenv

  desc "Unified configuration management for AI agents"
  homepage "https://github.com/DevArtsLab/tool-universal-ai-config"
  url "https://files.pythonhosted.org/packages/source/u/universal-ai-config/universal_ai_config-0.1.0.tar.gz"
  sha256 "REPLACE-WITH-SDIST-SHA256"
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    system bin/"ai-config", "--help"
  end
end
```

Get the sdist URL and sha256 from the PyPI release page
(`pypi.org/project/universal-ai-config/#files`). Update them on each release.
Alternatively, generate the formula automatically with
`brew bump-formula-pr` or homebrew's `poet` tooling.

## User Installation

Once released, users can install with any of:

```bash
uv tool install universal-ai-config       # or: uvx ai-config
pipx install universal-ai-config
pip install universal-ai-config
curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/install.sh | bash
```

Or download a standalone binary from the releases page.

## Uninstallation

```bash
curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/uninstall.sh | bash
```

Removes venv, uv, and pipx installs. Config files in `~/.agents/` are
preserved unless `--remove-config` is passed.

## Verification Checklist

- [ ] PyPI trusted publisher configured (or `PYPI_API_TOKEN` secret set)
- [ ] GitHub `pypi` environment created
- [ ] Tag pushed triggers `publish.yml` successfully
- [ ] `uvx ai-config --help` works from PyPI
- [ ] Release binaries download and run (`ai-config-* --help`)
- [ ] install.sh works on a clean machine (uv, pipx, and bare-python paths)

## Security Considerations

- OIDC trusted publishing avoids long-lived PyPI tokens
- All downloads use HTTPS
- Pin `actions/*` and `pypa/gh-action-pypi-publish` by tag (current practice:
  major version tags); consider SHA pinning for stricter supply-chain control
