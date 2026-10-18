# Container Release Security, Provenance & Rollback Guide

This document describes the container artifact versioning, immutable digest pinning, base image security, Software Bill of Materials (SBOM), and rollback procedures for `cf-tunnel-sync` and `cf-tunnel-dashboard`.

---

## 1. Versioning & Immutability

### Semantic Versioning (SemVer)
Releases strictly adhere to Semantic Versioning (`MAJOR.MINOR.PATCH`):
- **MAJOR:** Incompatible API or structural breaking changes (by design, `cf-docker-tunnel-sync` maintains strict zero-breaking-change backwards compatibility).
- **MINOR:** Backward-compatible features, observability enhancements, and new ingress capabilities.
- **PATCH:** Backward-compatible bugfixes and security updates.

### Tag Strategy & `latest` Semantics
| Tag Format | Example | Description | Recommended Environment |
|---|---|---|---|
| Immutable Patch Tag | `:1.19.0` | Pinned to a specific immutable code release | **Production** |
| Floating Minor Tag | `:1.19` | Automatically tracks latest patch within minor version | Staging / Non-prod |
| Floating Major Tag | `:1` | Tracks latest release in major branch | Testing / Dev |
| Floating Latest Tag | `:latest` | Always tracks the newest published stable release | Quickstart / Evaluations |
| Immutable Digest (SHA256) | `@sha256:7f...` | Exact cryptographic image manifest digest | High-security Production |

> [!TIP]
> In production environments, pin your containers to an explicit version tag (e.g., `hapheus/cf-tunnel-sync:1.19.0`) or an immutable digest (`@sha256:...`) to guarantee deterministic deployments and prevent unexpected updates during automated pulls.

---

## 2. Supply Chain Security & SBOM

### Base Image Pinning & Hardening
- Container images are built on official Python slim base images running with unprivileged security boundaries where possible.
- Virtual environments (`uv`) are self-contained and strip non-production build tooling.
- Containers can operate with a read-only root filesystem (`read_only: true`), utilizing `/tmp` for temporary lockfiles and sockets.

### SBOM (Software Bill of Materials)
Container artifacts are cataloged with automated SBOM generation:
- Standard formats: **SPDX JSON** or **CycloneDX JSON**.
- Inspection using `syft` or Docker CLI:
  ```bash
  # Inspect container dependencies using Docker SBOM CLI plugin
  docker sbom hapheus/cf-tunnel-sync:1.19.0

  # Or using Syft directly
  syft hapheus/cf-tunnel-sync:1.19.0 -o spdx-json=cf-tunnel-sync-sbom.spdx.json
  ```

### Vulnerability Scanning
All published artifacts can be scanned before deployment using standard security scanners:
```bash
# Scan image with Trivy
trivy image --severity HIGH,CRITICAL hapheus/cf-tunnel-sync:1.19.0

# Scan image with Docker Scout
docker scout cves hapheus/cf-tunnel-sync:1.19.0
```

---

## 3. Rollback Procedures

Because `cf-tunnel-sync` is stateless and operates via an idempotent state-reconciler, rolling back to an earlier version is safe and straightforward.

### Rollback Workflow

1. **Identify the Last Known-Good Version or Digest:**
   Locate your previous pinned release tag (e.g. `v1.18.0` or digest `sha256:...`).

2. **Verify Configuration Compatibility:**
   All configuration options and label namespaces maintain 100% backward compatibility. When downgrading from a newer release to an older release, ensure that any features exclusive to the newer version (such as newly introduced Access Policy tags or custom ingress rules) are either disabled or use their fallback defaults.

3. **Preflight Verification (Recommended):**
   Before restarting the live sync service, run preflight validation using the target rollback version:
   ```bash
   docker run --rm --env-file .env \
     -e PREFLIGHT_ONLY=true \
     -v /var/run/docker.sock:/var/run/docker.sock:ro \
     hapheus/cf-tunnel-sync:1.18.0
   ```
   Confirm that all 7 preflight stages pass cleanly:
   - Environment variables validated
   - Cloudflare API authentication & tunnel access confirmed
   - DNS Zone verified
   - Docker daemon accessibility confirmed
   - Port conflicts & ingress labels parsed

4. **Update Docker Compose & Recreate Container:**
   Update your `docker-compose.yml`:
   ```yaml
   services:
     cf-tunnel-sync:
       image: hapheus/cf-tunnel-sync:1.18.0 # Rolled back from 1.19.0
       restart: unless-stopped
       env_file: .env
       volumes:
         - /var/run/docker.sock:/var/run/docker.sock:ro
   ```
   Apply the change:
   ```bash
   docker compose up -d cf-tunnel-sync
   ```

5. **Monitor First Reconcile:**
   Check the logs of the rolled-back container:
   ```bash
   docker compose logs -f cf-tunnel-sync
   ```
   Verify that:
   - Initial synchronization runs without errors.
   - `ChangePlan` indicates state reconciliation without unexpected mass deletions.
   - Prometheus metrics endpoint `GET /metrics` reports `cf_tunnel_sync_reconcile_status == 1`.
