import tomllib
from pathlib import Path

from fincopilot import __version__


def test_package_imports_and_has_version():
    assert __version__ == "0.2.0"


def test_version_matches_pyproject():
    """A deploy host installs the project by the pyproject version and caches the
    build under it. If the two drift, the app can run code that is no longer in
    the repository -- which is exactly how Phase 15 first reached the live site.
    """
    meta = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["version"] == __version__
