"""Isolated contracts for dependency rules."""

import ast
import subprocess
import sys

from tests.paths import REPO_ROOT


def test_dependency_direction_stays_explicit():
    package = REPO_ROOT / "src" / "tunnel_sync"
    for layer in ("domain", "application"):
        for path in (package / layer).glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    name = node.module or ""
                    assert not name.startswith(
                        ("app", "tunnel_sync.web", "tunnel_sync.adapters", "fastapi", "httpx")
                    ), path
                elif isinstance(node, ast.Import):
                    assert all(not alias.name.startswith(("app", "fastapi", "httpx")) for alias in node.names), path
            if layer == "domain":
                assert all(
                    not isinstance(node, ast.Import)
                    or all(alias.name not in {"os", "time", "uuid"} for alias in node.names)
                    for node in ast.walk(tree)
                ), path


def test_import_does_not_start_threads_connect_sockets_or_reconfigure_root_logging(tmp_path):
    code = """
import socket, threading, logging
def forbidden(*args, **kwargs):
    raise AssertionError('Import attempted background work or a connection')
socket.socket.connect = forbidden
threading.Thread.start = forbidden
before = list(logging.getLogger().handlers)
import app
assert list(logging.getLogger().handlers) == before
assert app.app.state.services.runtime.snapshot()['status'] == 'Initializing'
"""
    # The managed editable installation supplies imports, independent of the checkout cwd.
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env={}, check=True, capture_output=True, text=True)
