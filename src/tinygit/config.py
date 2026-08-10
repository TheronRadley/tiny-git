"""Minimal configuration system for Tiny Git (.tinygit/config)."""

from __future__ import annotations

import configparser
import io
from pathlib import Path

from tinygit.errors import ConfigurationError
from tinygit.utils import atomic_write_file


class ConfigManager:
    """Manages repository configuration (.tinygit/config)."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.config_path = repo_root / ".tinygit" / "config"
        self._parser = configparser.ConfigParser()

    def exists(self) -> bool:
        """Check if config file exists."""
        return self.config_path.is_file()

    def _load(self) -> None:
        self._parser.clear()
        if self.config_path.is_file():
            self._parser.read(self.config_path, encoding="utf-8")

    def _save(self) -> None:
        buf = io.StringIO()
        self._parser.write(buf)
        atomic_write_file(self.config_path, buf.getvalue())

    def get(self, key: str, default: str | None = None) -> str | None:
        """Get a configuration value by dotted key (e.g. 'user.name')."""
        self._load()
        parts = key.split(".", 1)
        if len(parts) != 2:
            raise ConfigurationError(key)
        section, option = parts
        if self._parser.has_option(section, option):
            return self._parser.get(section, option)
        return default

    def set(self, key: str, value: str) -> None:
        """Set a configuration value by dotted key (e.g. 'user.name')."""
        self._load()
        parts = key.split(".", 1)
        if len(parts) != 2:
            raise ConfigurationError(key)
        section, option = parts
        if not self._parser.has_section(section):
            self._parser.add_section(section)
        self._parser.set(section, option, value)
        self._save()

    def get_user_info(self) -> tuple[str, str]:
        """Get author name and email, defaulting to sensible defaults."""
        name = self.get("user.name", "Ron")
        email = self.get("user.email", "ron@example.com")
        assert name is not None and email is not None
        return name, email
