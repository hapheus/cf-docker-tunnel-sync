"""Preserve historical app imports and ASGI/CLI invocation."""

import sys

if __name__ == "__main__":
    from tunnel_sync.runtime.cli import main

    main()
else:
    from tunnel_sync.compat import app as _module

    sys.modules[__name__] = _module
