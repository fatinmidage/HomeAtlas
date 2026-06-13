"""Compatibility alias for :mod:`home_atlas.infra.db_isolation`."""

import sys

from home_atlas.infra import db_isolation as _impl
from home_atlas.infra.db_isolation import *  # noqa: F403

sys.modules[__name__] = _impl
