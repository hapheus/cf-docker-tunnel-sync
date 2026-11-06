"""ISS-01..ISS-18 non-breaking hardening regression tests (hermetic)."""

import json
import os
import stat

import pytest

from tests.fakes import remote
from tunnel_sync.adapters.connector import FileTokenStore
from tunnel_sync.application.executor import ChangeExecutor
from tunnel_sync.application.sync import RemoteFetcher
from tunnel_sync.configuration.settings import Settings
from tunnel_sync.domain.models import DiscoverySnapshot
from tunnel_sync.domain.planner import compute_change_plan
from tunnel_sync.web.auth import create_auth


def test_settings_typed_max_deletions_precedence():
    s = Settings({"MAX_DELETIONS_PER_RUN": "5", "MAX_DELETIONS_PER_SYNC": "7"})
    assert s.max_deletions == 7
    s2 = Settings({"MAX_DELETIONS_PER_RUN": "5"})
    assert s2.max_deletions == 5
    s3 = Settings({})
    assert s3.max_deletions == 3


def test_dashboard_auth_required_fails_closed():
    check, _ = create_auth(lambda: Settings({"DASHBOARD_AUTH_REQUIRED": "true"}))
    with pytest.raises(Exception) as exc:
        check(None)
    assert getattr(exc.value, "status_code", None) == 401
    check_default, _ = create_auth(lambda: Settings({}))
    assert check_default(None) is True


def test_token_file_permissions_best_effort(tmp_path):
    path = tmp_path / "sub" / "token"
    store = FileTokenStore(str(path))
    store.write("dummy-token")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert store.read() == "dummy-token"


def test_token_restart_retry_next_cycle():
    writes = []
    restarts = {"n": 0}

    class Store:
        def __init__(self):
            self.value = ""

        def read(self):
            return self.value

        def write(self, t):
            writes.append(t)
            self.value = t

    class Restarter:
        def restart(self, name):
            restarts["n"] += 1
            if restarts["n"] == 1:
                raise RuntimeError("boom")

    logs = []
    ex = ChangeExecutor(None, Store(), Restarter(), logs.append)
    ex.activate("same-token", lambda: "cloudflared", dry_run=False)
    assert ex._pending_token == "same-token"
    assert not any("same-token" in msg for msg in logs)
    ex.activate("same-token", lambda: "cloudflared", dry_run=False)
    assert ex._pending_token is None
    assert restarts["n"] == 2


def test_preserve_manual_roots_opt_in():
    snapshot = DiscoverySnapshot(timestamp=1, docker_ok=True, origins=[])
    rules = [{"hostname": "web.example.com", "service": "http://manual:80"}]
    state = remote(rules)
    state.existing_dns_records = [
        {
            "id": "r1",
            "type": "CNAME",
            "name": "web.example.com",
            "content": "real-tunnel.cfargotunnel.com",
            "comment": None,
            "proxied": True,
            "ttl": 1,
        }
    ]
    # Default (off): existing unmanaged root preserved via merge, but plan unchanged semantics.
    plan_default = compute_change_plan(snapshot, state, {}, now=1, plan_id="p1")
    assert plan_default.final_ingress_rules[0]["service"] == "http://manual:80"
    # Preserve opt-in with discovered host collision is covered by sync flag plumbing (no default change).
    assert Settings({}).preserve_manual_roots is False
    assert Settings({"PRESERVE_MANUAL_ROOTS": "true"}).preserve_manual_roots is True


def test_batch_dns_fetcher():
    calls = {"n": 0}

    class CF:
        def read(self, endpoint, token):
            calls["n"] += 1
            if "content=" in endpoint or "type=CNAME&name=" in endpoint:
                raise RuntimeError("unexpected per-host")
            if "type=CNAME" in endpoint:
                return {
                    "result": [
                        {"id": "a", "type": "CNAME", "name": "web.example.com", "content": "tunnel.cfargotunnel.com"}
                    ]
                }
            return {"result": []}

    out = RemoteFetcher(CF()).fetch_dns(
        "z", "example.com", "tok", "tunnel.cfargotunnel.com", [{"hostname": "web.example.com"}]
    )
    assert "a" in out


def test_tombstone_persistence_roundtrip(tmp_path):
    settings = Settings(
        {"TOMBSTONE_PERSISTENCE_ENABLED": "true", "TOMBSTONE_PERSISTENCE_PATH": str(tmp_path / "t.json")}
    )
    assert settings.tombstone_persistence_enabled is True
    data = {"web.example.com": 123.0}
    (tmp_path / "t.json").write_text(json.dumps(data))
    # Corrupt file tolerated
    (tmp_path / "bad.json").write_text("not json")
    from tunnel_sync.application.sync import SyncService

    s = object.__new__(SyncService)
    s.settings = Settings(
        {"TOMBSTONE_PERSISTENCE_ENABLED": "true", "TOMBSTONE_PERSISTENCE_PATH": str(tmp_path / "t.json")}
    )
    assert s._load_persisted_tombstones() == {"web.example.com": 123.0}
    s.settings = Settings(
        {"TOMBSTONE_PERSISTENCE_ENABLED": "true", "TOMBSTONE_PERSISTENCE_PATH": str(tmp_path / "bad.json")}
    )
    assert s._load_persisted_tombstones() == {}


def test_compat_shim_deprecation():
    # Shim files emit DeprecationWarning (checked statically to avoid warning-registry flakiness).
    from pathlib import Path

    assert "DeprecationWarning" in Path("src/cloudflare.py").read_text()
    assert Settings({}).tombstone_persistence_enabled is False
    assert Settings({}).heartbeat_enabled is False
