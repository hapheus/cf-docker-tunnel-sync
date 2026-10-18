# Backward Compatibility Contract & Upgrade Guidelines

## 1. Absolute Backward-Compatibility Contract (P0)

`cf-docker-tunnel-sync` strictly adheres to a **Zero Breaking Changes** policy for all existing deployments:

* **Additive Only:** New features, environment variables, Docker labels, API response fields, and deployment examples are strictly additive and optional. Existing services will never require re-creation, relabeling, or configuration updates to upgrade.
* **Auto-Discovery of Credentials:** `CLOUDFLARE_ACCOUNT_ID` is strictly optional and automatically discovered from the domain zone or API token. Existing configurations specifying `CLOUDFLARE_ACCOUNT_ID` continue to work unchanged.
* **Preserve Runtime Defaults:** Default behavior for published ports, shared network requirements (`REQUIRE_SHARED_NETWORK=false`), container discovery, deletion semantics, and polling intervals remain strictly unchanged across releases.
* **Preserve Remote Infrastructure:** The daemon never deletes, renames, overwrites, or claims ownership of pre-existing or unmanaged Cloudflare DNS records, ingress rules, or tunnels.
* **Keep Legacy Topologies Supported:** Single-compose, multi-compose, custom networks, and companion dashboards remain first-class supported topologies.
* **API & Dashboard Decoupling Guarantee:** The embedded web interface (`/` and `/dashboard`) remains available by default. Standalone companion dashboard setups (`hapheus/cf-tunnel-dashboard`) communicate strictly over documented HTTP API endpoints (`/api/*`) without accessing the Docker socket or Cloudflare credentials.
* **Rollback Guarantee:** Upgrades are stateless and require zero irreversible migrations. Downgrading container images to a previous release tag is always safe.

---

## 2. Supported Baseline Deployments (Golden Matrix)

The test suite validates upgrade-in-place stability against the following canonical topologies:

1. **Single-Compose Topology (`examples/01-quickstart-single-stack`):**
   * Central gateway daemon and application container in a single `docker-compose.yml`.
2. **Multi-Compose Topology (`examples/02-multi-stack-external-net`):**
   * Central gateway stack communicating with independent application Compose stacks across a shared bridge network (`cf-tunnel-net`).
3. **Socket-Proxy Topology (`examples/03-secure-socket-proxy`):**
   * TCP-isolated Docker socket proxy deployments (`DOCKER_HOST=tcp://docker-socket-proxy:2375`) without mounting `/var/run/docker.sock` directly.
4. **Multi-Account & Tunnel Scoping (`examples/05-multi-account`):**
   * Scoped tunnel instances using `cf.tunnel.name` or `cf.tunnel.account` labels.
5. **Custom Network Architectures:**
   * Custom bridge or overlay networks configured via `CUSTOM_NETWORK` / `CF_NETWORK_NAME`.
6. **Historical Label Aliases:**
   * Seamless backwards-compatibility for `tunnel.hostname`, `tunnel.port`, `tunnel.service`, `cloudflared.hostname`, etc.

---

## 3. Upgrade-in-Place Verification Drill

To upgrade an existing installation:

```bash
# 1. Pull the candidate release image
docker compose pull

# 2. Re-create the sync daemon container
docker compose up -d

# 3. Verify daemon startup and zero unexpected mutations
docker compose logs --tail=100 cf-tunnel-sync
curl -s http://localhost:8080/health
curl -s http://localhost:8080/api/status | jq .
```

Reconciliation must be completely idempotent: if running containers have not changed, the sync engine executes 0 DNS creations, 0 DNS updates, and 0 DNS deletions.

---

## 4. Rollback Drill

If an issue occurs or an operator chooses to rollback:

```bash
# 1. Pin the service image to the previous release tag in docker-compose.yml
# image: hapheus/cf-tunnel-sync:v1.16.0

# 2. Re-create the container with the previous tag
docker compose up -d

# 3. Verify health
curl -s http://localhost:8080/health
```

No database migrations, volume rollbacks, or Cloudflare DNS repairs are required.

