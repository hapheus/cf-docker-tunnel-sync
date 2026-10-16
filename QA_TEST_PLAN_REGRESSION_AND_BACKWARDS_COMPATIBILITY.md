# QA Test Plan: Zero Breaking Changes & Legacy Backwards Compatibility Regression

## 1. Executive Summary & Objective
- **Directive:** Strict Zero Breaking Changes.
- **Scope:**
  1. Regression testing against existing `docker-compose.yml` topologies (single-compose, dual/multi-compose gateway + service stacks, multi-account scoped gateways).
  2. Complete backwards compatibility for legacy container label schemas (`cloudflared.*`, bare shorthand `proto`, `port`, `notlsverify`).
  3. Precedence hierarchy ensuring modern labels take priority while legacy labels function seamlessly as fallbacks.

---

## 2. Scope of Testing & Regression Matrix

### A. Docker Compose Topology Compatibility Matrix

| Environment / Topology | Compose File | Key Characteristics | Status |
| :--- | :--- | :--- | :--- |
| **Single-Compose (Baseline)** | `examples/01-single-compose/docker-compose.yml` | Sibling `cloudflared`, `cf-tunnel-sync`, `cf-tunnel-dashboard`, and `web-app` on shared bridge network | **PASSED** |
| **Multi-Compose (Dual/Split Stacks)** | `examples/02-multi-compose/` | Isolated gateway stack with separate service stacks (`whoami`, `website`, `api`) across external network | **PASSED** |
| **Multi-Account Scoped Gateways** | `examples/03-multi-account/` | Gateway instances filtered by `CLOUDFLARE_TUNNEL_NAME` and `cf.tunnel.name` | **PASSED** |
| **Root Default Deployment** | `docker-compose.yml` | Standard distribution configuration | **PASSED** |

### B. Label Compatibility & Fallback Hierarchy Matrix

| Configuration | Modern Key (`cf.tunnel.*`) | Legacy Key (`cloudflared.*`) | Bare / Shorthand Key | Current App Status |
| :--- | :--- | :--- | :--- | :--- |
| **Hostname** | `cf.tunnel.hostname` | `cloudflared.hostname` | - | Partial (Domain fallback missing) |
| **Domain Fallback** | `cf.tunnel.domain` | `cloudflared.domain` | - | **Missing in `cloudflared.`** |
| **Port** | `cf.tunnel.port` | `cloudflared.port` | `port` | **Missing in `cloudflared.` & Shorthand** |
| **Protocol / Scheme** | `cf.tunnel.protocol`, `cf.tunnel.proto`, `cf.tunnel.scheme` | `cloudflared.protocol`, `cloudflared.proto`, `cloudflared.scheme` | `proto`, `protocol`, `scheme` | **Missing in `cloudflared.` & Shorthand** |
| **Direct Service URL** | `cf.tunnel.service` | `cloudflared.service` | `service` | **Missing in `cloudflared.` & Shorthand** |
| **TLS Verify (`noTLSVerify`)** | `cf.tunnel.notlsverify`, `cf.tunnel.notls_verify`, `cf.tunnel.tls.verify` | `cloudflared.notlsverify`, `cloudflared.notls_verify`, `cloudflared.tls.verify` | `notlsverify`, `notls_verify` | **Missing in `cloudflared.` & Shorthand** |
| **Tunnel Scoping** | `cf.tunnel.name`, `cf.tunnel.tunnel` | `cloudflared.name`, `cloudflared.tunnel` | - | **Missing in `cloudflared.`** |

---

## 3. Precedence Rules (Deterministic Resolution)
When multiple label variations are defined on a single container, resolution MUST follow:
1. **Modern Prefix:** `cf.tunnel.<key>` (Highest priority)
2. **Legacy Cloudflared Prefix:** `cloudflared.<key>` (Secondary priority)
3. **Bare Shorthand:** `<key>` (Tertiary fallback)

---

## 4. Test Suite Implementation
- **Test File:** `cf-tunnel-sync/test_regression_backwards_compatibility.py`
- **Runner:** `pytest` / `unittest` (`python -m unittest discover -s cf-tunnel-sync`)
- **Hermetic:** 100% mocked Docker daemon and environment state, no external network requirements.
- **Current Run Results:**
  - Topology regression: 4/4 passing (Single, Multi-compose, Scoped tunnels, Precedence).
  - Legacy label regression: 8/8 failing on unhandled legacy labels.
  - Overall: 4 Passed, 8 Failed (Red phase for legacy aliases).

---

## 5. Acceptance Criteria for Developer Sign-Off
1. All 12 tests in `test_regression_backwards_compatibility.py` must pass with exit code `0`.
2. Existing 26 tests in `test_app.py` and `test_ingress_labels.py` must continue to pass (zero regression on Issue #3 and baseline sync).
3. Total test suite passes: 38/38 tests passing across the repository.
