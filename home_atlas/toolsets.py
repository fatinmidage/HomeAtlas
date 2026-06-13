"""Compatibility alias for :mod:`home_atlas.app.toolsets`."""

import sys

from home_atlas.app import toolsets as _impl
from home_atlas.app.toolsets import *  # noqa: F403

sys.modules[__name__] = _impl
