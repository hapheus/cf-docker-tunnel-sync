"""The sole external mutation workflow, including provisioning and activation."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from tunnel_sync.application.ports import CloudflareWriter, ConnectorRestarter, TokenStore
from tunnel_sync.domain.models import BlastRadiusExceededError, ChangePlan, DnsActionType


@dataclass(frozen=True)
class DeletionPolicy:
    maximum: int = 3
    ratio: float | None = None
    allow_mass: bool = False

    def validate(self, plan: ChangePlan) -> int:
        count = max(plan.summary.ingress_deletes, plan.summary.dns_deletes)
        error = None
        if not self.allow_mass:
            if count > self.maximum:
                error = f"Mass deletion threshold exceeded (planned: {count}, limit: {self.maximum})"
            total = plan.summary.total_services_discovered + count
            if self.ratio is not None and self.ratio > 0 and total and count / total > self.ratio:
                error = f"Mass deletion ratio exceeded (planned ratio: {count / total:.2f}, limit: {self.ratio:.2f})"
        if error:
            raise BlastRadiusExceededError(
                f"[SAFETY_GUARD] BLAST RADIUS GUARD: {error}. Sync aborted.", count, self.maximum
            )
        return count


@dataclass(frozen=True)
class OperationResult:
    resource: str
    action: str
    target: str
    status: Literal["succeeded", "failed", "skipped"]
    reason: str = ""

    @property
    def attempted(self) -> bool:
        return self.status in ("succeeded", "failed")


@dataclass
class ExecutionResult:
    operations: list[OperationResult] = field(default_factory=list)

    def failed(self, resource: str) -> bool:
        return any(op.resource == resource and op.status == "failed" for op in self.operations)


class ChangeExecutor:
    """Preserve partial progress: ingress failure does not prevent DNS attempts.

    No rollback is attempted. The next cycle re-reads remote state and converges.
    Dry-run permission is checked before each mutation workflow.
    """

    def __init__(
        self,
        writer: CloudflareWriter,
        token_store: TokenStore | None,
        restarter: ConnectorRestarter | None,
        log: Callable[[str], None],
        record: Callable[[OperationResult], None] | None = None,
    ):
        self.writer, self.token_store, self.restarter = writer, token_store, restarter
        self.log = log
        self.record = record or (lambda result: None)

    def provision(self, account_id: str, name: str, token: str, *, dry_run: bool) -> str | None:
        if dry_run:
            return None
        result = self.writer.mutate(
            f"/accounts/{account_id}/cfd_tunnel", token, method="POST", data={"name": name, "config_src": "cloudflare"}
        )
        tunnel_id = result["result"]["id"]
        self.log(f"✅ Created Tunnel: {tunnel_id}")
        return tunnel_id

    def activate(self, tunnel_token: str, connector: Callable[[], str], *, dry_run: bool) -> None:
        if dry_run:
            return
        if self.token_store is None or self.restarter is None:
            raise RuntimeError("Connector activation requires token storage and restart capabilities")
        try:
            try:
                old_token = self.token_store.read()
            except OSError:
                old_token = ""
            if old_token == tunnel_token:
                return
            self.token_store.write(tunnel_token)
            self.log("🔑 Updated Cloudflare Tunnel Token in shared volume")
            try:
                name = connector()
                self.restarter.restart(name)
                self.log(f"🔄 Triggered restart for cloudflared container ({name})")
            except Exception as error:
                self.log(f"Notice restarting cloudflared: {error}")
        except Exception as error:
            self.log(f"Notice writing tunnel token: {error}")

    def execute(
        self,
        plan: ChangePlan,
        token: str,
        account_id: str,
        *,
        policy: DeletionPolicy,
        current_config: dict[str, Any] | None = None,
        dry_run: bool = False,
        fail_fast: bool = False,
    ) -> ExecutionResult:
        result = ExecutionResult()
        if dry_run or plan.dry_run:
            for ingress_change in plan.ingress_changes:
                result.operations.append(
                    OperationResult(
                        "ingress", ingress_change.action.value, ingress_change.hostname or "", "skipped", "dry-run"
                    )
                )
            for change in plan.dns_changes:
                result.operations.append(
                    OperationResult("dns", change.action.value, change.hostname, "skipped", "dry-run")
                )
            return result
        try:
            deletions = policy.validate(plan)
        except BlastRadiusExceededError as error:
            self.log(str(error))
            raise
        if policy.allow_mass and deletions:
            self.log(
                f"[SAFETY_GUARD] Mass deletion override active (ALLOW_MASS_DELETIONS=true). Proceeding with {deletions} planned deletions."
            )

        def attempt(resource, action, target, endpoint, method, payload=None):
            try:
                self.writer.mutate(endpoint, token, method=method, data=payload)
            except Exception as error:
                operation = OperationResult(resource, action, target, "failed", str(error))
                result.operations.append(operation)
                self.record(operation)
                if fail_fast:
                    raise
            else:
                operation = OperationResult(resource, action, target, "succeeded")
                result.operations.append(operation)
                self.record(operation)

        # Compare freshly read provider state rather than a previous-run cache.
        ingress_changed = (
            current_config.get("ingress", []) != plan.final_ingress_rules
            if current_config is not None
            else plan.summary.ingress_creates + plan.summary.ingress_updates + plan.summary.ingress_deletes > 0
        )
        if ingress_changed:
            config = deepcopy(current_config or {})
            config["ingress"] = deepcopy(plan.final_ingress_rules)
            attempt(
                "ingress",
                "update",
                "ingress",
                f"/accounts/{account_id}/cfd_tunnel/{plan.tunnel_id}/configurations",
                "PUT",
                {"config": config},
            )

        for change in plan.dns_changes:
            if change.action == DnsActionType.PROTECT:
                operation = OperationResult("dns", "protect", change.hostname, "skipped", change.reason)
                result.operations.append(operation)
                self.record(operation)
                continue
            if change.action not in (DnsActionType.CREATE, DnsActionType.UPDATE, DnsActionType.DELETE):
                continue
            endpoint = f"/zones/{plan.zone_id}/dns_records"
            if change.action == DnsActionType.DELETE:
                attempt("dns", "delete", change.hostname, f"{endpoint}/{change.record_id}", "DELETE")
                continue
            payload = {
                "type": change.record_type,
                "name": change.hostname,
                "content": change.target_content,
                "proxied": change.proxied,
                "ttl": change.ttl,
            }
            if change.target_comment:
                payload["comment"] = change.target_comment
            if change.action == DnsActionType.UPDATE:
                endpoint += f"/{change.record_id}"
            attempt(
                "dns",
                change.action.value,
                change.hostname,
                endpoint,
                "POST" if change.action == DnsActionType.CREATE else "PUT",
                payload,
            )
        return result
