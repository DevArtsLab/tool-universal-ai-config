"""The package version must stay in sync with pyproject.toml: publish.yml
validates the git tag against pyproject alone, so __version__ drifting would
ship a release that misreports itself."""

from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib

from universal_ai_config import __version__


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    version = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert __version__ == version
