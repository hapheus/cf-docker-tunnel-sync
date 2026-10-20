"""Read-only environment inspection, separate from sync execution."""

import logging
from typing import List, Optional

from tunnel_sync.domain.diagnostics import PreflightDiagnostic, mask_sensitive_text

logger = logging.getLogger("cf-tunnel-sync")


class PreflightService:
    def __init__(self, settings, cloudflare, docker, discovery):
        self.settings, self.cloudflare, self.docker, self.discovery = settings, cloudflare, docker, discovery

    def run(self, dry_run: bool = True) -> int:
        """Non-mutating preflight validation mode (Issue #48, #97).

        Guarantees that only read-only queries are executed against Docker and Cloudflare.
        Never calls mutator methods.
        Returns 0 on valid environment, 1 on error with actionable What/Why/How to fix messages.
        Zero secrets leaked in terminal logs.
        """
        logger.info("==================================================")
        logger.info("🔍 Starting Non-Mutating Preflight Validation (R01)")
        logger.info("==================================================")

        failed_checks = 0

        def _log_preflight_fail(check: str, what: str, why: str, fix: str, extra: Optional[List[str]] = None) -> None:
            secrets = list(extra or [])
            tok = self.settings.token
            if tok:
                secrets.append(tok)
            diag = PreflightDiagnostic(
                check_name=check,
                what_failed=what,
                why=why,
                how_to_fix=fix,
            )
            for line in diag.format_terminal(extra_secrets=secrets).splitlines():
                logger.error(line)

        # 1. Docker Socket Connectivity & Permissions
        try:
            ver_resp = self.docker.request("/version")
            if not ver_resp or not isinstance(ver_resp, dict):
                _log_preflight_fail(
                    "Docker Daemon Connectivity",
                    "Docker daemon API returned an invalid or empty response.",
                    "Unable to retrieve system version details from /var/run/docker.sock.",
                    "Ensure Docker socket is mounted at /var/run/docker.sock with read permissions.",
                )
                failed_checks += 1
            else:
                docker_version = ver_resp.get("Version", "unknown")
                logger.info(f"✅ [PREFLIGHT PASS] Docker daemon connected (Version: {docker_version}).")
        except Exception as e:
            _log_preflight_fail(
                "Docker Socket Connectivity",
                "Cannot connect to Docker daemon socket at /var/run/docker.sock.",
                f"Docker socket communication failed: {e}",
                "Ensure /var/run/docker.sock is mounted into the container (-v /var/run/docker.sock:/var/run/docker.sock:ro) and Docker daemon is running.",
            )
            failed_checks += 1

        # 2. Cloudflare API Token Validity & Permissions
        token = self.settings.token
        if not token:
            _log_preflight_fail(
                "Cloudflare API Token",
                "Cloudflare API token is missing.",
                "Neither CLOUDFLARE_API_TOKEN nor CLOUDFLARE_TOKEN environment variable is set.",
                "Set CLOUDFLARE_API_TOKEN environment variable with Zone:DNS:Edit and Account:Cloudflare Tunnel:Edit permissions.",
            )
            failed_checks += 1
        else:
            try:
                verify_resp = self.cloudflare.read("/user/tokens/verify", token, method="GET")
                status = verify_resp.get("result", {}).get("status")
                if status != "active":
                    _log_preflight_fail(
                        "Cloudflare API Token Verification",
                        f"Cloudflare API token verification returned non-active status: '{status}'.",
                        "The token is not active, may have expired, or is restricted by IP address in Cloudflare.",
                        "Verify in Cloudflare Dashboard (My Profile > API Tokens) that the token is Active and has Zone:DNS:Edit and Account:Cloudflare Tunnel:Edit permissions.",
                    )
                    failed_checks += 1
                else:
                    logger.info("✅ [PREFLIGHT PASS] Cloudflare API token verified and active.")
            except Exception as e:
                _log_preflight_fail(
                    "Cloudflare API Token Verification",
                    "Cloudflare API token verification failed.",
                    f"Cloudflare API error during token verification: {e}",
                    "Verify network connectivity to api.cloudflare.com and check CLOUDFLARE_API_TOKEN.",
                    extra=[token],
                )
                failed_checks += 1

        # 3. Target Cloudflare Zone and Tunnel ID
        domain = self.settings.domain
        if not domain:
            _log_preflight_fail(
                "Domain Configuration",
                "DOMAIN_NAME environment variable is not configured.",
                "A target root domain is required to find Cloudflare DNS zones and manage tunnel routes.",
                "Set DOMAIN_NAME=yourdomain.com in environment or compose file.",
            )
            failed_checks += 1
        elif token:
            try:
                zones_resp = self.cloudflare.read(f"/zones?name={domain}", token, method="GET")
                zones = zones_resp.get("result", [])
                if not zones:
                    _log_preflight_fail(
                        "Cloudflare Zone Resolution",
                        f"Zone for domain '{domain}' not found in Cloudflare account.",
                        f"No active DNS zone matching '{domain}' was returned for this account.",
                        "Verify DOMAIN_NAME matches a zone in your Cloudflare account and token has Zone:Read permission.",
                    )
                    failed_checks += 1
                else:
                    zone_id = zones[0]["id"]
                    logger.info(f"✅ [PREFLIGHT PASS] Cloudflare Zone verified for '{domain}' (Zone ID: {zone_id}).")

                    account_id = self.settings.get("CLOUDFLARE_ACCOUNT_ID")
                    if not account_id:
                        zone_account = zones[0].get("account", {})
                        account_id = zone_account.get("id")
                    if not account_id:
                        acc_resp = self.cloudflare.read("/accounts", token, method="GET")
                        accs = acc_resp.get("result", [])
                        if accs:
                            account_id = accs[0].get("id")

                    tunnel_name = self.settings.get("CLOUDFLARE_TUNNEL_NAME", "cf-docker-tunnel-sync").strip()
                    tunnel_id = self.settings.get("CLOUDFLARE_TUNNEL_ID")

                    if tunnel_id and account_id:
                        tun_resp = self.cloudflare.read(
                            f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}", token, method="GET"
                        )
                        tun = tun_resp.get("result")
                        if tun and not tun.get("deleted_at"):
                            logger.info(f"✅ [PREFLIGHT PASS] Cloudflare Tunnel ID '{tunnel_id}' verified.")
                        else:
                            _log_preflight_fail(
                                "Cloudflare Tunnel ID Lookup",
                                f"Cloudflare Tunnel ID '{tunnel_id}' not found or deleted.",
                                f"Tunnel ID '{tunnel_id}' does not exist in Cloudflare account '{account_id}' or is marked deleted.",
                                "Check CLOUDFLARE_TUNNEL_ID or create a new tunnel.",
                            )
                            failed_checks += 1
                    elif account_id:
                        tunnels_resp = self.cloudflare.read(
                            f"/accounts/{account_id}/cfd_tunnel?name={tunnel_name}&is_deleted=false",
                            token,
                            method="GET",
                        )
                        tuns = tunnels_resp.get("result", [])
                        if tuns:
                            logger.info(
                                f"✅ [PREFLIGHT PASS] Cloudflare Tunnel '{tunnel_name}' found (ID: {tuns[0]['id']})."
                            )
                        else:
                            _log_preflight_fail(
                                "Cloudflare Tunnel Lookup",
                                f"Cloudflare Tunnel '{tunnel_name}' does not exist.",
                                f"No active tunnel named '{tunnel_name}' was found in Cloudflare account '{account_id}'.",
                                f"Create tunnel '{tunnel_name}' in Cloudflare Zero Trust dashboard or run 'cloudflared tunnel create {tunnel_name}'.",
                            )
                            failed_checks += 1
            except Exception as e:
                _log_preflight_fail(
                    "Cloudflare Zone and Tunnel Inspection",
                    "Failed to verify Zone/Tunnel with Cloudflare API.",
                    f"Cloudflare API error during Zone/Tunnel inspection: {e}",
                    "Verify token permissions for Zone:Read and Cloudflare Tunnel:Read.",
                    extra=[token],
                )
                failed_checks += 1

        # 4. Network Inspection & Docker Container Discovery
        try:
            services, all_containers = self.discovery.discover()
            logger.info(
                f"✅ [PREFLIGHT PASS] Inspected Docker containers ({len(all_containers)} total containers, {len(services)} tunneled services)."
            )
        except Exception as e:
            safe_msg = mask_sensitive_text(str(e), [token] if token else None)
            logger.warning(f"⚠️ [PREFLIGHT WARN] Network inspection encountered an issue: {safe_msg}")

        logger.info("==================================================")
        if failed_checks == 0:
            logger.info("🎉 [PREFLIGHT SUCCESS] All preflight checks passed successfully. Zero mutations performed.")
            return 0
        else:
            logger.error(
                f"❌ [PREFLIGHT ABORT] Preflight failed with {failed_checks} error(s). Please review remedy messages above."
            )
            return 1
