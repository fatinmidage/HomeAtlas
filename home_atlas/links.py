"""Compatibility alias for :mod:`home_atlas.domain.links`."""

import sys

from home_atlas.domain import links as _impl
from home_atlas.domain.links import *  # noqa: F403

sys.modules[__name__] = _impl
