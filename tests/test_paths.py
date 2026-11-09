from pathlib import Path

import pytest

from pokeverse.paths import default_db_path


def test_default_db_path_respects_xdg_data_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert default_db_path() == tmp_path / "pokeverse" / "catalog.db"


def test_default_db_path_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert default_db_path() == Path.home() / ".local" / "share" / "pokeverse" / "catalog.db"


def test_the_app_uses_pokeverse_db_when_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from pokeverse.api import create_app

    db_path = tmp_path / "from-env.db"
    monkeypatch.setenv("POKEVERSE_DB", str(db_path))

    with create_app(runner=lambda work: None).state.catalogs():
        pass

    assert db_path.exists()
