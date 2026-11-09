"""Filesystem locations shared by the API and the CLI."""

import os
from pathlib import Path


def default_db_path() -> Path:
    """``POKEVERSE_DB`` is checked by callers; this is the fallback under ``XDG_DATA_HOME``."""
    data_home = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(data_home) / "pokeverse" / "catalog.db"
