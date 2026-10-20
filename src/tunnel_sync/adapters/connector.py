"""Filesystem token storage and Docker connector activation."""

import os


class FileTokenStore:
    def __init__(self, path: str = "/etc/cloudflared/token"):
        self.path = path

    def read(self) -> str:
        if not os.path.exists(self.path):
            return ""
        with open(self.path, encoding="utf-8") as handle:
            return handle.read().strip()

    def write(self, token: str) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(token)


class DockerConnectorRestarter:
    def __init__(self, request):
        self.request = request

    def restart(self, name: str) -> None:
        self.request(f"/containers/{name}/restart", method="POST")
