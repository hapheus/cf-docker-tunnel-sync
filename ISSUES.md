# ISSUES – cf-docker-tunnel-sync (v1.23.3)

Consolidated issue board from two independent analyses (architecture/quality + security/operations).
Create/deduplicated with review input from: **PM, PO, Lead Developer, Enterprise Architect, Security Engineer**.
Language: English (per CONTRIBUTING.md). Priorities: **P0** = fix before production / security-critical, **P1** = correct before scale, **P2** = hardening / tech debt.

> Scope note: No classic code-level critical bug (RCE, SQLi, SSRF, XSS, eval, pickle, shell injection) was found. All P0 items are design/operational risks, not exploitable code bugs. See "Security summary" below.

## Non-breaking constraint (binding for all issues below)

Every issue in this document **must be solvable without breaking changes**:

- No removal or rename of existing env vars, labels, API endpoints, CLI flags, or file paths.
- No change of a default value that would break an existing working deployment (bind address, auth mode, ownership policy, image tags in shipped code, sync timing).
- New stricter/safer behavior is introduced as **opt-in** (new env var, new compose profile, new example) or as **warn-only** (log warning + docs).
- Existing behavior remains the default; hardened behavior is available side-by-side and documented.
- Internal refactors must keep public interfaces, config precedence, and persisted formats backward compatible.
- Deprecation warnings are allowed; removal is out of scope and would require a separate major-version decision.

Where the original analysis proposed a breaking default change, this revision replaces it with the compatible alternative listed under "Non-breaking approach".

---

## Summary counts

| Priority | Security / Operations | Architecture / Quality | Unique issues |
|----------|----------------------|------------------------|---------------|
| P0 | 4 | 3 | 7 (1 overlap) |
| P1 | 6 | 6 | 12 |
| P2 | 0 | 4 | 4 |
| **Total** | **10** | **13** | **23 → 18 deduplicated** |

Deduplication: non-transactional sync, token-restart gap, in-memory state, shutdown timeout, and missing E2E tests appeared in both analyses and are merged into single issues below.

---

## Issue Board

| ID | Title | P | Owners (Lead) | Status | Breaking? |
|----|-------|---|---------------|--------|-----------|
| ISS-01 | Unfiltered Docker socket = host-root access | P0 | Security Eng. | Open | No – docs/warn/opt-in proxy |
| ISS-02 | Dashboard auth can be silently disabled / default-open | P0 | Security Eng. / Lead Dev | Open | No – warn + opt-in strict mode |
| ISS-03 | Floating `latest` images in examples & root Compose | P0 | Security Eng. / PM | Open | No – examples only |
| ISS-04 | Root Compose publishes 0.0.0.0:8080 | P0 | Security Eng. | Open | No – docs/warn, default unchanged |
| ISS-05 | Token file accessible via shared volume | P0 | Security Eng. | Open | No – perms tightening w/ fallback |
| ISS-06 | `SyncService.run_once` God-Object (485 lines) | P1 | Lead Dev / Enterprise Arch | Open | No – internal refactor |
| ISS-07 | Non-transactional, non-atomic sync (partial updates) | P1 | Lead Dev | Open | No – docs/observability |
| ISS-08 | Root-route collision overwrites manual routes | P1 | PO / Lead Dev | Open | No – preflight warn + opt-in policy |
| ISS-09 | Ownership adoption can hijack foreign DNS records | P1 | PO / Security Eng. | Open | No – logging + docs, default unchanged |
| ISS-10 | Token-restart gap (no retry after failed restart) | P1 | Lead Dev | Open | No – internal state retry |
| ISS-11 | In-memory state (tombstones/history reset on restart) | P1 | Enterprise Arch | Open | No – opt-in persistence |
| ISS-12 | Legacy dual structure (11 shims + `compat/` + double setup) | P1 | Lead Dev / Enterprise Arch | Open | No – freeze + warnings only |
| ISS-13 | N+1 Cloudflare DNS reads per service | P1 | Lead Dev | Open | No – internal optimization w/ fallback |
| ISS-14 | Scheduler shutdown timeout / unkillable worker | P1 | Lead Dev | Open | No – docs/watchdog opt-in |
| ISS-15 | No E2E tests against live Cloudflare/Docker | P1 | Lead Dev / PO | Open | No – CI only |
| ISS-16 | Weak lint/typecheck (Ruff `E,F,W,I` only, Mypy not strict) | P2 | Lead Dev | Open | No – warn-first, non-blocking |
| ISS-17 | Config as raw strings (no typed Settings properties) | P2 | Lead Dev | Open | No – internal, same env names/precedence |
| ISS-18 | Silent `except Exception: pass` hides failures | P2 | Lead Dev / Security Eng. | Open | No – debug logging + redaction |

---

## Detailed Issues

### ISS-01 – Unfiltered Docker socket = host-root access
- **Priority:** P0 · **Owner:** Security Engineer
- **Evidence:** `docker-compose.yml:32` (`/var/run/docker.sock:ro`), `docs/security.md`, `examples/03-secure-socket-proxy/`. `:ro` restricts filesystem access to the socket node, but HTTP POSTs over the socket can create/start privileged containers with host mounts.
- **Impact:** Anyone reaching the sync container/API (dashboard RCE, SSRF, leaked credentials) gains full host compromise.
- **Mitigation today:** Socket-proxy example exists (GET-only filter, no restart) but is not the default.
- **Non-breaking approach:** Do **not** change the shipped socket mount or disable restart. Keep raw socket as supported default for homelab compatibility. Add (a) prominent Quickstart/security docs recommending the socket-proxy example for untrusted networks, (b) a startup log warning when the socket is unfiltered (detected via env/docs hint, not by probing daemon), (c) fix example 03 so opting into the proxy is one copy-paste step. Proxy remains opt-in; auto-restart trade-off already documented.
- **Roles:** *Security Eng.:* P0 docs/warn. *PM:* No release blocker for homelab; risk note for WAN. *PO:* Quickstart step 1 prominence. *Lead Dev:* Warn-only check. *Enterprise Arch.:* Document least-privilege proxy as recommended target, not mandated default.

### ISS-02 – Dashboard auth can be silently disabled / default-open
- **Priority:** P0 · **Owner:** Security Engineer / Lead Developer
- **Evidence:** `src/tunnel_sync/web/auth.py:54-66` (no credentials + no `DASHBOARD_AUTH_ENABLED` → `return True`; `false` → open), `src/tunnel_sync/web/app.py` (`/health`, `/healthz`, `/ready` public; `/metrics` public unless `METRICS_AUTH_ENABLED=true`), `docker-compose.yml:35` publishes `0.0.0.0:8080`.
- **Impact:** Info disclosure (container names, hostnames, sync status via `sanitize_sync_state`) + unauthenticated `POST /api/sync` (DoS/state change) if exposed. Basic Auth over plain HTTP, no rate limiting.
- **Non-breaking approach:** Do **not** make auth mandatory by default (would break existing headless/loopback deployments). Instead: (a) startup warning when no credentials are configured **and** dashboard is enabled, (b) new opt-in strict-mode env var (e.g. `DASHBOARD_AUTH_REQUIRED=true`) that fails closed, off by default, (c) docs/TLS reverse-proxy guidance, (d) keep `/health` probes public (standard for orchestrators), document that `/api/status` and `/api/sync` should not be WAN-exposed without auth/TLS. No endpoint removal or auth-scheme change.
- **Roles:** *Security Eng.:* P0 warn + opt-in strict mode. *Lead Dev:* Warning + opt-in flag, preserve current precedence (incl. legacy `BASIC_AUTH_*` fallback). *PM:* Non-breaking hardening release, no forced migration. *PO:* Update docs/examples with strict-mode snippet. *Enterprise Arch.:* Note OIDC/TLS as future opt-in, not a migration requirement.

### ISS-03 – Floating `latest` images in examples & root Compose
- **Priority:** P0 · **Owner:** Security Engineer / PM
- **Evidence:** `cloudflare/cloudflared:latest`, `nginx:alpine`, `traefik/whoami:latest` in `docker-compose.yml`, `QUICKSTART.md`, `examples/`. Main image itself is digest-pinned (`cf-tunnel-sync/Dockerfile: python:3.11-alpine@sha256:...`), but examples are not.
- **Impact:** Supply-chain drift; unrepeatable deployments; compromised upstream tag propagates silently.
- **Non-breaking approach:** Examples/docs are not a runtime contract – pin example images by version/digest. Keep `latest` only in explicitly-quickstart snippets with a warning comment. Do not change the shipped sync image build or tag scheme. Add a CI check that warns (not fails) on `latest` in examples, so existing CI stays green.
- **Roles:** *Security Eng.:* P0 for examples. *PM:* Release checklist item, no user migration. *PO:* Fix examples. *Lead Dev:* Warn-only CI lint. *Enterprise Arch.:* Pinning policy for examples only.

### ISS-04 – Root Compose publishes 0.0.0.0:8080
- **Priority:** P0 · **Owner:** Security Engineer
- **Evidence:** `docker-compose.yml:34-35` (`"${DASHBOARD_BIND_ADDRESS:-0.0.0.0}:${DASHBOARD_PORT:-8080}:8090"`).
- **Impact:** Default-open dashboard on WAN if `docker compose up` run verbatim on a cloud host.
- **Non-breaking approach:** Do **not** change the default bind (would break users relying on LAN/WAN dashboard access). Instead: (a) comment in root Compose recommending `DASHBOARD_BIND_ADDRESS=127.0.0.1` for WAN hosts, (b) startup warning when bound non-loopback without auth (see ISS-02), (c) promote the existing headless example (no published ports) as the hardened alternative in README/Quickstart. Default stays `0.0.0.0` for compatibility.
- **Roles:** *Security Eng.:* P0 docs/warn. *PO:* README/Quickstart. *Lead Dev:* Warning only, no default change. *PM:* Communicate as guidance, not forced change. *Enterprise Arch.:* Network-exposure guideline.

### ISS-05 – Token file accessible via shared volume
- **Priority:** P0 · **Owner:** Security Engineer
- **Evidence:** `cf_token_data:/etc/cloudflared` shared volume (`docker-compose.yml:7,33`), `FileTokenStore` writes connector token; no explicit `0600` guarantee or volume ACL visible.
- **Impact:** Any container with volume access reads the Cloudflare tunnel token.
- **Non-breaking approach:** Best-effort permission tightening on write (`0600` file, `0700` dir where the FS allows) with silent fallback if `chmod` fails or owners differ – never fail the sync or break the connector read path. Both sync and `cloudflared` run as root in shipped Compose, so tightening is compatible. Document volume ACLs; Docker secrets remain an opt-in alternative, not a migration.
- **Roles:** *Security Eng.:* P0 best-effort perms. *Lead Dev:* `try/except OSError` chmod, no behavior change on failure. *PM:* Security checklist. *PO:* Document. *Enterprise Arch.:* Secret-management as opt-in.

### ISS-06 – `SyncService.run_once` God-Object (485 lines)
- **Priority:** P1 · **Owner:** Lead Developer / Enterprise Architect
- **Evidence:** `src/tunnel_sync/application/sync.py` – zone resolution, tunnel provisioning, DNS fetch (N+1), planning, execution, status mapping, metrics, notifications in one method.
- **Impact:** Testability, maintainability, bug-proneness; change risk for any fix.
- **Non-breaking approach:** Internal extraction only (`ZoneResolver`, `RemoteFetcher`, `StatusPublisher`). Keep `SyncService.run_once` signature, env vars, state keys, plan format, and log/event names identical. Refactor in small steps covered by existing integration tests; no API or config change.
- **Roles:** *Lead Dev:* P1 refactor. *Enterprise Arch.:* Module boundaries. *PM:* Schedule after P0s. *PO:* No user-facing change. *Security Eng.:* Verify safety invariants unchanged via existing contract tests.

### ISS-07 – Non-transactional, non-atomic sync (partial updates)
- **Priority:** P1 · **Owner:** Lead Developer
- **Evidence:** `ChangeExecutor.execute()` – ingress PUT then DNS mutations sequentially; ingress failure does not block DNS; documented in `docs/architecture-and-safety.md#current-limitations` (no rollback, retry from fresh state).
- **Impact:** Partial state (ingress updated, DNS failed) until next cycle; operators may misread "Sync" as atomic.
- **Non-breaking approach:** Keep convergence model exactly as-is. Improve observability only: ensure "Degraded" status, per-service stage status, and retry visibility are accurate and documented. Do not introduce rollback, 2PC, or ordering changes that alter failure semantics.
- **Roles:** *Lead Dev:* Observability only. *PM:* Align expectations. *PO:* Troubleshooting docs. *Enterprise Arch.:* Keep convergence; no saga. *Security Eng.:* No partial-failure data leak.

### ISS-08 – Root-route collision overwrites manual routes
- **Priority:** P1 · **Owner:** PO / Lead Developer
- **Evidence:** `src/tunnel_sync/domain/planner.py` + `ingress.py:merge_ingress()` – first root route per hostname is managed; manual path/catch-all preserved, but a manual root for the same hostname is replaced.
- **Impact:** Existing tunnel users lose manual root forwards on upgrade.
- **Non-breaking approach:** Keep current merge semantics. Add preflight listing of manual root routes (read-only) and an **opt-in** `PRESERVE_MANUAL_ROOTS` policy (off by default) that, when enabled by the user, skips managed replacement. Default planner output unchanged.
- **Roles:** *PO:* Docs + onboarding checklist. *Lead Dev:* Preflight warning + opt-in flag. *PM:* Support-ticket anticipator. *Enterprise Arch.:* Ownership model. *Security Eng.:* No direct impact.

### ISS-09 – Ownership adoption can hijack foreign DNS records
- **Priority:** P1 · **Owner:** PO / Security Engineer
- **Evidence:** Default `adopt_and_manage` policy; `OwnershipTagging.parse_status()` → `ADOPTED` when CNAME points to this tunnel's target with no/empty comment and is locally requested. Doku warns: "Missing/empty/null comments do not establish ownership".
- **Impact:** Records managed by other tools targeting the same tunnel get tagged/rewritten.
- **Non-breaking approach:** Keep `adopt_and_manage` as default (changing it would break existing homelab setups). Add explicit log/event on every adoption, and document `strict_tagged_only` as opt-in for existing/shared zones. No policy default change.
- **Roles:** *PO:* Documentation. *Security Eng.:* P1 logging. *Lead Dev:* Adoption log events. *PM:* User communication. *Enterprise Arch.:* Policy UX.

### ISS-10 – Token-restart gap (no retry after failed restart)
- **Priority:** P1 · **Owner:** Lead Developer
- **Evidence:** `ChangeExecutor.activate()` – if token written but `restarter.restart()` fails, next cycle sees unchanged token and skips restart. Healthcheck does not wait for token/connector.
- **Impact:** First-boot tunnel stays down until manual `docker restart cloudflared`.
- **Non-breaking approach:** Track "token written, restart pending" in existing in-memory state and retry the restart on the next cycle. No env var, API, or timing default change. Healthcheck semantics unchanged; connector health may be surfaced in status output only.
- **Roles:** *Lead Dev:* P1 fix. *PO:* First-boot UX. *PM:* vNext feature. *Enterprise Arch.:* Activation state machine. *Security Eng.:* Retry must not log tokens.

### ISS-11 – In-memory state (tombstones/history reset on restart)
- **Priority:** P1 · **Owner:** Enterprise Architect
- **Evidence:** Tombstones, history, caches in memory; token file persists. `docs/architecture-and-safety.md` notes reset on restart.
- **Impact:** Grace periods restart after crash; delayed deletions; flapping protection weakened; metrics gaps.
- **Non-breaking approach:** Keep in-memory default. Add **opt-in** tombstone persistence (new env var, off by default, e.g. to a file on the existing token volume) that is ignored if absent/corrupt and never blocks sync. No change to current reset behavior for existing users.
- **Roles:** *Enterprise Arch.:* P1. *Lead Dev:* Opt-in persistence with tolerant load. *PM:* Trade-off vs. complexity. *PO:* Operator expectations. *Security Eng.:* Persisted state must contain no secrets; validate format on load.

### ISS-12 – Legacy dual structure (11 shims + `compat/` + double setup)
- **Priority:** P1 · **Owner:** Lead Developer / Enterprise Architect
- **Evidence:** `src/app.py`, `src/cloudflare.py`, … (11 shims) + `src/tunnel_sync/compat/` + `pyproject.toml` double setup (`py-modules` vs. `packages.find`). Architecture tests enforce direction.
- **Impact:** Newcomer confusion; maintenance burden; import ambiguity.
- **Non-breaking approach:** **Freeze, do not remove.** Keep all shims and `compat/` fully supported. Add deprecation warnings pointing to canonical `tunnel_sync.*` imports, document canonical paths, and forbid new code in `compat/`. Removal is explicitly out of scope for this issue; any future removal would be a separate major-version proposal.
- **Roles:** *Lead Dev:* P1 freeze + warnings. *Enterprise Arch.:* Long-term support statement. *PM:* Communicate "supported indefinitely, canonical path preferred". *PO:* Migration guide (voluntary). *Security Eng.:* Security fixes must land in both canonical and compat paths.

### ISS-13 – N+1 Cloudflare DNS reads per service
- **Priority:** P1 · **Owner:** Lead Developer
- **Evidence:** `SyncService.run_once()` – one `GET /zones/{id}/dns_records?name=...` per service plus tunnel config read; 15s timeout/retries each.
- **Impact:** 50+ services = 50+ sequential requests; slow cycles; Cloudflare rate limits.
- **Non-breaking approach:** Internal optimization only: batch fetch (list CNAMEs for zone, filter locally) with automatic fallback to per-host reads if batch fails or pagination is incomplete, so results are identical in all cases. No API, config, or timing default change. Rate-limit backoff already exists via `RetryPolicy`.
- **Roles:** *Lead Dev:* P1 perf fix. *PM:* NFR target. *PO:* No UX change. *Enterprise Arch.:* API-usage budget. *Security Eng.:* Batch fetch must stay zone-scoped.

### ISS-14 – Scheduler shutdown timeout / unkillable worker
- **Priority:** P1 · **Owner:** Lead Developer
- **Evidence:** `Scheduler.close(timeout=45.0)`; Python cannot forcibly stop blocked worker threads; Docker event thread + `to_thread(run_once)` may overrun.
- **Impact:** Container kill during shutdown; incomplete sync.
- **Non-breaking approach:** Document the 45s timeout and idempotent shutdown; add opt-in heartbeat log for long-running syncs (no new required timeout, no behavior change on shutdown path). Do not change `close()` signature or default timeout.
- **Roles:** *Lead Dev:* P1 docs + heartbeat. *PM:* Ops runbook. *PO:* Troubleshooting. *Enterprise Arch.:* Lifecycle design. *Security Eng.:* Shutdown must not leave token file inconsistent (atomic write already).

### ISS-15 – No E2E tests against live Cloudflare/Docker
- **Priority:** P1 · **Owner:** Lead Developer / PO
- **Evidence:** 15.8k LOC tests (`unit/`, `contracts/`, `property/`, `architecture/`, `integration/` with fakes) but hermetic only; daily image verification is not E2E.
- **Impact:** Real-API pagination/rate-limit/race conditions untested.
- **Non-breaking approach:** CI-only addition: nightly **opt-in** E2E suite (sandbox account/zone, disposable tunnel) skipped by default, requiring explicit secrets. No change to default test suite or shipped code.
- **Roles:** *Lead Dev:* P1. *PO:* Acceptance criteria. *PM:* CI cost/benefit. *Enterprise Arch.:* Test pyramid. *Security Eng.:* Sandbox token scoping.

### ISS-16 – Weak lint/typecheck configuration
- **Priority:** P2 · **Owner:** Lead Developer
- **Evidence:** Ruff `select = ["E","F","W","I"]` only (no `B` bugbear, `S` bandit, `UP`, `SIM`); Mypy not strict; `except Exception: pass` in several places (e.g. account lookup, socket cleanup).
- **Impact:** Latent bugs, security issues missed.
- **Non-breaking approach:** Enable `B,S` in CI as **warn-first / non-blocking** (continue-on-error), fix findings incrementally, only promote to required after the codebase is clean. Mypy `--strict` as opt-in local check, not a merge gate. No existing check becomes stricter in a breaking way.
- **Roles:** *Lead Dev:* P2. *Security Eng.:* Review Bandit findings. *PM:* Low priority. *PO:* None. *Enterprise Arch.:* Quality gates.

### ISS-17 – Config as raw strings (no typed Settings properties)
- **Priority:** P2 · **Owner:** Lead Developer
- **Evidence:** `settings.get("DRY_RUN", "false").lower() in ("true","1","yes")` repeated in 5+ places; only `domain`/`token`/`dry_run` are typed properties.
- **Impact:** Inconsistent bool/number parsing; `MAX_DELETIONS_PER_SYNC` vs `MAX_DELETIONS_PER_RUN` precedence confusion.
- **Non-breaking approach:** Add typed properties that wrap the **existing** env names, defaults, and precedence exactly (including the `MAX_DELETIONS_PER_SYNC` > `MAX_DELETIONS_PER_RUN` fallback). No env var added/removed/renamed; behavior identical, covered by existing config tests.
- **Roles:** *Lead Dev:* P2. *Enterprise Arch.:* Config schema. *PM:* None. *PO:* Docs stay aligned. *Security Eng.:* Validate numeric/bool bounds without changing defaults.

### ISS-18 – Silent `except Exception: pass` hides failures
- **Priority:** P2 · **Owner:** Lead Developer / Security Engineer
- **Evidence:** Account lookup fallback (`sync.py`), socket cleanup, JSON parse fallbacks in Cloudflare client (`resp.text` logging may leak raw errors).
- **Impact:** Misdiagnosed outages; potential secret leakage in logs.
- **Non-breaking approach:** Replace bare `pass` with `logger.debug(..., exc_info=False)` including redacted context; never log raw `resp.text` – use `redact_sensitive_string` consistently. Log level and control flow unchanged; no new required log output for operators.
- **Roles:** *Lead Dev:* P2. *Security Eng.:* P2 (log secrets). *PM:* None. *PO:* Better error messages. *Enterprise Arch.:* Logging standard.

---

## Role Statements

### PM (Product Manager)
All P0s are solvable as **non-breaking hardening**: docs, warnings, opt-in strict modes, and example pins – no forced migration, no release-blocker for existing homelab users. ISS-02 and ISS-04 explicitly keep current defaults; hardened behavior is opt-in. Sequence: P0 docs/warnings first (days), then token-restart retry (ISS-10) and batch DNS (ISS-13) as vNext improvements. Non-transactional sync and in-memory state remain accepted product trade-offs – do not promise atomicity or persistence in docs; both stay opt-in where offered.

### PO (Product Owner)
Operators get: (1) socket-proxy as clearly recommended opt-in, (2) dedicated-tunnel + preflight onboarding for existing configs, (3) `strict_tagged_only` as documented opt-in for shared zones (default unchanged), (4) first-boot fixed via restart retry without any config change. Quickstart/Examples gain hardened snippets alongside existing ones; nothing existing is removed or re-defaulted. Troubleshooting covers partial sync (ISS-07), root-route collisions (ISS-08), and tombstone behavior after restart (ISS-11) in plain language.

### Lead Developer
Refactor order: P0 warnings/opt-ins first (ISS-01, ISS-02, ISS-04, ISS-05), then contained P1 fixes (ISS-10 restart retry, ISS-13 batch DNS with fallback). SyncService extraction (ISS-06) after P0s, strictly internal. Legacy shims are frozen, not removed (ISS-12). Ruff `B,S` warn-first (ISS-16) and typed Settings with identical precedence (ISS-17) incrementally. Adoption logging (ISS-09) and debug logging with redaction (ISS-18) are quick wins. Nightly E2E is opt-in CI only (ISS-15).

### Enterprise Architect
The layered design (configuration / domain / application / adapters / runtime / web, capability-separated readers/writers, deterministic planner) is preserved. Architectural decisions are all additive: (a) socket-proxy as recommended opt-in trust boundary (ISS-01), (b) opt-in strict auth mode, default unchanged (ISS-02), (c) opt-in tombstone persistence, in-memory default unchanged (ISS-11), (d) legacy freeze with canonical-path guidance, no removal (ISS-12). Non-transactional convergence remains the model; no distributed transactions. Every refactor keeps public interfaces and config precedence intact.

### Security Engineer
No code-level critical vulnerability was found. Deployment defaults remain as-is for compatibility, so WAN safety relies on **guidance + warnings + opt-ins**: socket-proxy recommendation (ISS-01), strict auth opt-in + TLS guidance (ISS-02), pinned example images (ISS-03), loopback bind recommendation without changing the default (ISS-04), best-effort `0600` token perms with fallback (ISS-05), redacted logging everywhere (ISS-18), and adoption-event logging (ISS-09). Verify Cosign signatures for published images; SBOM generation can be added to the publish workflow as a non-breaking CI improvement.

---

## Security Summary (cross-cutting)

- **Code-level:** No RCE/SQLi/SSRF/XSS/deserialization issues. Auth uses `secrets.compare_digest`. `sanitize_sync_state` redacts sensitive keys and strips `_`-prefixed internals. CSP is strict (`script-src 'self'`, no inline). Hostname validation is RFC 1123 compliant. No `eval`/`exec`/`pickle`/shell invocation in production code.
- **Exposure boundaries:** Docker socket, shared token volume, published dashboard port, and plain-HTTP Basic Auth are the four boundaries to tighten – all via docs, warnings, and opt-ins per ISS-01, ISS-02, ISS-04, ISS-05. No boundary is removed or re-defaulted.
- **Supply chain:** Main image is digest-pinned and built from `uv.lock` deterministically; examples and `latest` tags are the gap (ISS-03, examples only). Publish workflow signs with Cosign but does not explicitly request SBOM – adding SBOM is a non-breaking CI change.

---

## Proposed sequencing (all non-breaking)

1. **Immediate (P0 docs/warnings/opt-ins):** ISS-01, ISS-02, ISS-03, ISS-04, ISS-05 – warnings, strict-mode opt-in, example pins, bind-address guidance, token perms.
2. **Next release (P1 behavior, additive):** ISS-10 (token-restart retry), ISS-13 (batch DNS with fallback), ISS-08/09 (preflight + adoption logging, opt-in policy), ISS-15 (nightly opt-in E2E).
3. **Refactor track (P1/P2, internal only):** ISS-06 (God-Object extraction), ISS-12 (legacy freeze + warnings), ISS-14 (shutdown docs/heartbeat), ISS-11 (opt-in persistence decision), ISS-16/17/18 (quality gates, warn-first).

---

*Generated from joint PM/PO/LeadDev/EnterpriseArch/SecurityEng review of cf-docker-tunnel-sync v1.23.3, revised for non-breaking resolution. File references are to the audited tree.*
