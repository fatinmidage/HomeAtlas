"""Compatibility entrypoint for :mod:`home_atlas.interfaces.cli`."""

import sys

from home_atlas.interfaces import cli as _impl
from home_atlas.interfaces.cli import *  # noqa: F403

if __name__ == "__main__":
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
