from __future__ import annotations

import os

import pytest

from home_atlas.config import Settings
from home_atlas.db_isolation import verify_readonly_isolation


def test_verify_skipped_when_no_readonly_url():
    settings = Settings(_env_file=None, database_url="sqlite:///test.db", readonly_database_url="")
    result = verify_readonly_isolation(settings)
    assert result["status"] == "skipped"


def test_verify_skipped_for_non_postgres():
    settings = Settings(_env_file=None, database_url="sqlite:///test.db", readonly_database_url="sqlite:///ro.db")
    result = verify_readonly_isolation(settings)
    assert result["status"] == "skipped"


_SKIP_REASON = (
    "set HOME_ATLAS_INTEGRATION_DATABASE_URL and HOME_ATLAS_INTEGRATION_READONLY_URL "
    "to run database isolation tests"
)


@pytest.mark.skipif(
    not os.getenv("HOME_ATLAS_INTEGRATION_DATABASE_URL")
    or not os.getenv("HOME_ATLAS_INTEGRATION_READONLY_URL"),
    reason=_SKIP_REASON,
)
def test_verify_readonly_blocks_writes():
    settings = Settings(
        _env_file=None,
        database_url=os.environ["HOME_ATLAS_INTEGRATION_DATABASE_URL"],
        readonly_database_url=os.environ["HOME_ATLAS_INTEGRATION_READONLY_URL"],
    )
    result = verify_readonly_isolation(settings)
    assert result["status"] == "ok"
    assert result["blocked"] == 3


@pytest.mark.skipif(
    not os.getenv("HOME_ATLAS_INTEGRATION_DATABASE_URL"),
    reason="set HOME_ATLAS_INTEGRATION_DATABASE_URL to run database isolation tests",
)
def test_verify_raises_when_role_can_write():
    owner_url = os.environ["HOME_ATLAS_INTEGRATION_DATABASE_URL"]
    settings = Settings(
        _env_file=None,
        database_url=owner_url,
        readonly_database_url=owner_url,
    )
    with pytest.raises(RuntimeError, match="readonly database role can execute writes"):
        verify_readonly_isolation(settings)
