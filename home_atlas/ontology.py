"""Compatibility alias for :mod:`home_atlas.domain.ontology`."""

import sys

from home_atlas.domain import ontology as _impl
from home_atlas.domain.ontology import *  # noqa: F403

sys.modules[__name__] = _impl
