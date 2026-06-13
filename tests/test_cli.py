from __future__ import annotations

import json

from sqlalchemy import create_engine, text

from home_atlas.interfaces import cli
from home_atlas.interfaces.cli import dual_smoke, init_db, smoke
from home_atlas.core.config import Settings
from home_atlas.core.llm_config import normalize_model_name


def test_smoke_runs_through_write_read_audit(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'home_atlas.db'}"
    settings = Settings(_env_file=None, database_url=database_url, token_map={"you-token": "你"})
    init_db(settings)

    exit_code = smoke(settings, token="you-token", item="护照", location="保险柜抽屉")

    assert exit_code == 0


def test_dual_smoke_checks_writer_actor(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'home_atlas.db'}"
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        token_map={"you-token": "你", "spouse-token": "配偶"},
        agent_mode="rules",
    )
    init_db(settings)

    exit_code = dual_smoke(
        settings,
        writer_token="you-token",
        reader_token="spouse-token",
        item="双端烟测护照",
        location="双端烟测保险柜",
    )

    assert exit_code == 0


def test_settings_token_map_accepts_json() -> None:
    settings = Settings(_env_file=None, token_map=json.loads('{"you-token":"你"}'))
    assert settings.token_map == {"you-token": "你"}


def test_settings_accepts_agent_mode() -> None:
    settings = Settings(_env_file=None, agent_mode="rules")
    assert settings.agent_mode == "rules"


def test_settings_accepts_llm_model_from_env_alias() -> None:
    settings = Settings(_env_file=None, HOME_ATLAS_LLM_MODEL="deepseek:deepseek-chat")
    assert settings.llm_model == "deepseek:deepseek-chat"


def test_settings_accepts_app_llm_api_key_alias() -> None:
    settings = Settings(_env_file=None, HOME_ATLAS_LLM_API_KEY="test-key")
    assert settings.llm_api_key == "test-key"


def test_settings_accepts_provider_api_key_alias() -> None:
    settings = Settings(_env_file=None, DEEPSEEK_API_KEY="test-key")
    assert settings.llm_api_key == "test-key"


def test_deepseek_bare_model_name_is_normalized() -> None:
    assert normalize_model_name("deepseek-v4-flash") == "deepseek:deepseek-v4-flash"
    assert normalize_model_name("deepseek:deepseek-chat") == "deepseek:deepseek-chat"


def test_alembic_upgrade_accepts_percent_encoded_database_url(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_upgrade(config, revision):
        seen["revision"] = revision
        seen["url"] = config.get_main_option("sqlalchemy.url")

    monkeypatch.setattr(cli.command, "upgrade", fake_upgrade)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://home_atlas:p%25ss@localhost/home_atlas",
    )

    cli._run_alembic_upgrade(settings)

    assert seen == {
        "revision": "head",
        "url": "postgresql+psycopg://home_atlas:p%25ss@localhost/home_atlas",
    }


def test_alembic_upgrade_runs_with_percent_in_sqlite_path(tmp_path) -> None:
    db_dir = tmp_path / "p%ss"
    db_dir.mkdir()
    db_path = db_dir / "home_atlas.db"
    settings = Settings(_env_file=None, database_url=f"sqlite:///{db_path}")

    cli._run_alembic_upgrade(settings)

    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        version = connection.execute(
            text("select value from schema_metadata where key = 'ontology_schema_version'")
        ).scalar_one()
        alembic_version = connection.execute(text("select version_num from alembic_version")).scalar_one()
    assert db_path.exists()
    assert version == "2"
    assert alembic_version == "0009_timezone_aware_timestamps"
