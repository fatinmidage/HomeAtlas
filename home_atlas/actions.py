"""Compatibility alias for :mod:`home_atlas.app.actions`."""

import sys

from home_atlas.app import actions as _impl
from home_atlas.app.actions import *  # noqa: F403

sys.modules[__name__] = _impl
