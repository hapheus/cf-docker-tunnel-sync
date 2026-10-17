# SAFE-01: Audit of DNS & Ingress Ownership Logic Before Destructive Operations

**Audit Target:** `cf-tunnel-sync/reconcile.py`, `cf-tunnel-sync/cloudflare.py`  
**Milestone:** M0 (Compatibility Baseline & Upgrade Safety - v1.14.0)  
**Tracking Issue:** [#89](https://github.com/hapheus/cf-docker-tunnel-sync/issues/89)  
**Date:** October 17, 2026  
**Status:** Completed & Formalized  

---

## 1. Executive Summary

This audit evaluates the resource ownership model, collision handling, and deletion semantics in `cf-docker-tunnel-sync`. The primary objective is to prove that destructive operations (deletions and updates) can never unintentionally overwrite, claim, or delete unmanaged DNS records or Cloudflare Tunnel ingress rules.

---

## 2. Current Architecture & Mechanisms

### 2.1 Ownership Classification Model
In `reconcile.py`, ownership is evaluated per DNS record via `OwnershipTagging.parse_status()`:

```python
class OwnershipStatus(str, Enum):
    OWNED = "owned"  # Exact match: CNAME points to tunnel target AND comment == cf-tunnel-sync:<tunnel_name>
    ADOPTED = "adopted"  # Points to tunnel target, but lacks tag comment; active locally
    UNMANAGED = "unmanaged"  # Points to tunnel target, but lacks tag comment; not active locally
    FOREIGN_TUNNEL = (
        "foreign_tunnel"  # Points to tunnel target, but comment has a different tunnel tag (cf-tunnel-sync:<other>)
    )
    UNRELATED = "unrelated"  # Not a CNAME or points to an external non-tunnel target
```

### 2.2 Reconcile Policies (`OwnershipPolicy`)
1. **`ADOPT_AND_MANAGE` (Default runtime policy):**
   * Pre-existing CNAMEs that point to the tunnel target and match a discovered container hostname are adopted (tagged with comment `cf-tunnel-sync:<tunnel_name>`).
   * Unmanaged CNAMEs pointing elsewhere or unowned records are never touched.
2. **`STRICT_TAGGED_ONLY`:**
   * Only records explicitly created and tagged by this tunnel are ever modified or deleted. Untagged records are marked `PROTECT` and skipped.
3. **`LEGACY_UNRESTRICTED`:**
   * Fallback compatibility mode for legacy deployments without comment tagging.

---

## 3. Findings & Identified Edge Cases

### Finding 1: Asymmetry Between DNS Comments and Ingress Rules
* **DNS Records:** Cloudflare DNS API supports metadata via the `comment` field (up to 100 characters). This allows reliable, stateless ownership tagging (`cf-tunnel-sync:<tunnel_name>`).
* **Ingress Rules:** The Cloudflare Tunnel Configuration API (`/accounts/{id}/cfd_tunnel/{id}/configurations`) does **not** support comments, tags, or metadata fields on individual ingress rules.
* **Risk:** Ingress rules for hostnames not discovered in Docker containers cannot be natively tagged as "unmanaged" or "managed by another tool".
* **Current Mitigation:**
  * `RECONCILE_GRACE_PERIOD_SECONDS` (default 60s) places missing hostnames in a tombstone state rather than deleting them immediately.
  * Ingress rules are preserved as `NOOP` during the grace period.

### Finding 2: Unrelated and External DNS Records Fail-Safe
* CNAME records pointing to external CDN targets (e.g., `cdn.example.com` -> `external.net`) are classified as `OwnershipStatus.UNRELATED`.
* A records (e.g., apex `example.com` -> `198.51.100.1`) and TXT records that do not carry the `cf-tunnel-sync:` prefix are immediately skipped and never added to deletion change sets.

### Finding 3: Multi-Account & Multi-Tunnel Hostname Collisions
* If two independent tunnels attempt to expose the same hostname on the same Cloudflare Zone, Cloudflare DNS allows only one CNAME record for that hostname.
* `reconcile.py` detects when a DNS record points to a foreign tunnel target (`OwnershipStatus.UNRELATED` or `OwnershipStatus.FOREIGN_TUNNEL`) and aborts / protects that record, preventing cross-tunnel route hijacking.

---

## 4. Invariants for Milestone 2 Implementation

1. **Strict DNS Invariant:** No DNS record shall be deleted unless its type is `CNAME`, its target matches the active tunnel's `tunnel_target`, and its comment matches the active tunnel's tag (`cf-tunnel-sync:<tunnel_name>`).
2. **Strict Ingress Invariant:** Any remote ingress rule not matching discovered Docker containers must observe the mandatory grace period tombstone. An opt-in unmanaged ingress preservation whitelist will be added in M2.
3. **Blast Radius Invariant:** Any planned deletions exceeding `MAX_DELETIONS_PER_SYNC` (default 5) or `MAX_DELETION_RATIO` (default 50%) MUST abort the reconciliation cycle with `BlastRadiusExceededError` and emit a security metric alert.
