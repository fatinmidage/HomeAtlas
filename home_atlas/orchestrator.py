"""Compatibility alias for :mod:`home_atlas.app.orchestrator`."""

import sys

from home_atlas.app import orchestrator as _impl
from home_atlas.app.orchestrator import *  # noqa: F403

sys.modules[__name__] = _impl
