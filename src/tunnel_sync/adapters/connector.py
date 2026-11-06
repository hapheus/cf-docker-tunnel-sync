"""Filesystem token storage and Docker connector activation."""

import logging
import os

logger = logging.getLogger("cf-tunnel-sync")


class FileTokenStore:
    def __init__(self, path: str = "/etc/cloudflared/token"):
        self.path = path

    def read(self) -> str:
        if not os.path.exists(self.path):
            return ""
        with open(self.path, encoding="utf-8") as handle:
            return handle.read().strip()

    def write(self, token: str) -> None:
        parent = os.path.dirname(self.path)
        os.makedirs(parent, exist_ok=True)
        # ISS-05 (best-effort, non-breaking): tighten permissions. Never fail sync on chmod errors.
        for target, mode in ((parent, 0o700), (self.path, 0o600)):
            try:
                if target == parent or os.path.exists(target):
                    os.chmod(target, mode)
            except OSError:
                # Best-effort only (ISS-05); sync continues in-memory on failure.
                logger.debug("ISS-05: token chmod skipped for %s", target, exc_info=False)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(token)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            logger.debug("ISS-05: token chmod skipped after write", exc_info=False)


class DockerConnectorRestarter:
    def __init__(self, request):
        self.request = request

    def restart(self, name: str) -> None:
        self.request(f"/containers/{name}/restart", method="POST")
