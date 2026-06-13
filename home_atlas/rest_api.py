"""Compatibility alias for :mod:`home_atlas.interfaces.rest_api`."""

import sys

from home_atlas.interfaces import rest_api as _impl
from home_atlas.interfaces.rest_api import *  # noqa: F403

sys.modules[__name__] = _impl
