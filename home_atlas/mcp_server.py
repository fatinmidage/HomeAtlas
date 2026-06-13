"""Compatibility entrypoint for :mod:`home_atlas.interfaces.mcp_server`."""

import sys

from home_atlas.interfaces import mcp_server as _impl
from home_atlas.interfaces.mcp_server import *  # noqa: F403

if __name__ == "__main__":
    _impl.main()

sys.modules[__name__] = _impl
