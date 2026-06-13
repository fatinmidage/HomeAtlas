from __future__ import annotations

from pathlib import Path

import pytest

from home_atlas.infra.backup import backup_database, postgresql_cli_url
from home_atlas.core.config import Settings


def test_postgresql_cli_url_strips_sqlalchemy_driver() -> None:
    url = postgresql_cli_url("postgresql+psycopg://home_atlas:secret@localhost:5432/home_atlas")

    assert url == "postgresql://home_atlas:secret@localhost:5432/home_atlas"


def test_backup_requires_postgresql_url(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'home_atlas.db'}")

    with pytest.raises(ValueError):
        backup_database(settings, tmp_path / "backup.dump")
