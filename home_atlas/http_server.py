"""Compatibility entrypoint for :mod:`home_atlas.interfaces.http_server`."""

import sys

from home_atlas.interfaces import http_server as _impl
from home_atlas.interfaces.http_server import *  # noqa: F403

if __name__ == "__main__":
    _impl.main()

sys.modules[__name__] = _impl
