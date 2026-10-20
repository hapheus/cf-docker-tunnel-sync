## Description
<!-- Provide a concise summary of the changes and link the relevant GitHub Issue(s). -->
Fixes #

---

### 🛡️ Backward Compatibility & Non-Breaking Contract (P0 Gate)
*Mandatory checklist: All pull requests must guarantee zero breaking changes to existing deployments.*

- [ ] **Existing inputs touched:** Document any touched environment variables, labels, CLI flags, volumes, or networks. (If none, state "None").
- [ ] **Runtime defaults preserved:** Verified that runtime defaults (e.g., ports, network requirements, discovery fallbacks, polling intervals) remain 100% unchanged for existing setups.
- [ ] **Cloudflare resource safety:** Verified that reconciliation remains idempotent and will never overwrite, claim, or delete unmanaged or pre-existing DNS records or ingress rules.
- [ ] **Rollback plan & drill verified:** Verified that rolling back by downgrading the image tag requires no manual database or schema repairs.
- [ ] **Regression test coverage:** Added or updated hermetic unit tests (`test_*.py`) and verified full test suite passes.

---

### 🧪 Verification Steps
1. Run hermetic unit tests:
   ```bash
   uv run pytest
   ```
2. Run compatibility baseline and golden fixtures:
   ```bash
   uv run pytest tests/contracts/test_compatibility_baseline.py tests/contracts/test_compat_baseline_fixtures.py
   ```
