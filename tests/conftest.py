"""Shared pytest configuration and fixtures for Tiny Git test suite.

Every test uses isolated temporary directories provided by pytest's tmp_path
fixture, ensuring tests are deterministic and never touch global state.
"""

from pathlib import Path

import pytest

from tinygit.repository import Repository


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    """Fixture providing an initialized, clean Tiny Git repository in an isolated temporary directory."""
    return Repository.init(tmp_path, default_branch="main")
