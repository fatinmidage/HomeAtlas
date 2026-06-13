"""Compatibility alias for :mod:`home_atlas.app.agents`."""

import sys

from home_atlas.app import agents as _impl
from home_atlas.app.agents import *  # noqa: F403

sys.modules[__name__] = _impl
