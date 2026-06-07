from __future__ import annotations

import json

from home_atlas.cli import init_db, smoke
from home_atlas.config import Settings


def test_smoke_runs_through_write_read_audit(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'home_atlas.db'}"
    settings = Settings(database_url=database_url, token_map={"you-token": "你"})
    init_db(settings)

    exit_code = smoke(settings, token="you-token", item="护照", location="保险柜抽屉")

    assert exit_code == 0


def test_settings_token_map_accepts_json() -> None:
    settings = Settings(token_map=json.loads('{"you-token":"你"}'))
    assert settings.token_map == {"you-token": "你"}
