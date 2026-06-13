"""Compatibility alias for :mod:`home_atlas.app.dispatcher`."""

import sys

from home_atlas.app import dispatcher as _impl
from home_atlas.app.dispatcher import *  # noqa: F403

sys.modules[__name__] = _impl
