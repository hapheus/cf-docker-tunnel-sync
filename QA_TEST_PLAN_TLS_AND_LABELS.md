# QA Test Plan: HTTPS Origins, TLS Verification, and Label Validation

## 1. Overview
This test plan specifies the test requirements, edge cases, and automated test cases for:
1. HTTPS / TLS container origin services
2. `noTLSVerify` configuration in Cloudflare Tunnel ingress rules (`originRequest`)
3. Resilience, sanitation, and validation of Docker container labels

Target Component: `cf-tunnel-sync` (`app.py`)  
Automated Test Specification: `cf-tunnel-sync/proposed_test_ingress_labels.py`

---

## 2. Test Cases & Verification Matrix

### Suite 1: HTTPS & TLS Origins

| ID | Title | Input / Docker Labels | Expected Behavior |
|---|---|---|---|
| **TC-TLS-01** | Explicit HTTPS service URL | `cf.tunnel.service="https://app:8443"` | Ingress rule `service` preserved as `https://app:8443`. |
| **TC-TLS-02** | Protocol/Scheme override | `cf.tunnel.port="8443"`, `cf.tunnel.proto="https"` (or `cf.tunnel.scheme="https"`) | Ingress rule `service` formatted as `https://{container_name}:8443`. |
| **TC-TLS-03** | Port 443 default inference | Container exposes port 443 with no explicit service URL | Ingress rule `service` defaults to `https://{container_name}:443` or documented behavior. |

### Suite 2: `noTLSVerify` Configuration & Idempotency

Cloudflare Tunnel ingress rules support TLS verification bypass for internal/self-signed certificates via the `originRequest` block:
```json
{
  "hostname": "vault.example.com",
  "service": "https://vault:8200",
  "originRequest": {
    "noTLSVerify": true
  }
}
```

| ID | Title | Input / Docker Labels | Expected Behavior |
|---|---|---|---|
| **TC-NOTLS-01** | Enable `noTLSVerify` | `cf.tunnel.notlsverify="true"` (or `"1"`, `"yes"`, `True`) | Ingress rule sent to Cloudflare API includes `"originRequest": {"noTLSVerify": true}`. |
| **TC-NOTLS-02** | Alternative label formats | `cf.tunnel.originRequest.noTLSVerify="true"`, `cf.tunnel.tlsverify="false"` | Correctly recognized as enabling `noTLSVerify: true`. |
| **TC-NOTLS-03** | Default / Disabled behavior | Label absent or `cf.tunnel.notlsverify="false"` | Ingress rule does NOT contain `"noTLSVerify": true`. |
| **TC-NOTLS-04** | Ingress rule idempotency | Repeated sync run with identical `originRequest` | `_last_ingress` equality check succeeds; no duplicate `PUT /configurations` API calls triggered. |

### Suite 3: Label Sanitation & Invalid Input Handling

| ID | Title | Input / Docker Labels | Expected Behavior |
|---|---|---|---|
| **TC-INV-01** | Non-numeric port string | `cf.tunnel.port="abc"` or `"8080xyz"` | Graceful fallback to container exposed port (or 80) with a logged warning; must never generate invalid URL like `http://host:abc`. |
| **TC-INV-02** | Out-of-range port | `cf.tunnel.port="70000"` or `cf.tunnel.port="-1"` | Validation error logged; container skipped or port normalized. |
| **TC-INV-03** | Hostname with protocol scheme | `cf.tunnel.hostname="https://app.example.com"` | Sanitized by stripping protocol (`app.example.com`) to prevent DNS CNAME record failure. |
| **TC-INV-04** | Empty / whitespace hostname | `cf.tunnel.hostname="   "` | Skipped safely from ingress rule list; no empty DNS records created. |
| **TC-INV-05** | Duplicate hostname collision | Two containers define `cf.tunnel.hostname="app.example.com"` | Deduplicated deterministically (first container registered, collision logged) to prevent Cloudflare HTTP 400 rejection. |
| **TC-INV-06** | Null/None Labels | Docker API returns `"Labels": null` | Handled safely via `c.get('Labels') or {}`; no `AttributeError`. |
| **TC-INV-07** | Unsupported URI scheme | `cf.tunnel.service="javascript:alert(1)"` or `ftp://...` | Rejected with validation log; prevented from being pushed to Cloudflare API. |

---

## 3. Implementation Handoff & Acceptance Criteria
- [ ] Automated tests in `proposed_test_ingress_labels.py` pass 100% when run with `pytest` / `unittest`.
- [ ] Existing 10 unit tests in `test_app.py` remain 100% passing (zero regression).
- [ ] No unhandled exceptions in the sync loop when encountering malformed container labels.
