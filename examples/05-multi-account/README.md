# Example 05: Multi-Account & Multi-Domain Architecture

This example demonstrates how to run **multiple distinct Cloudflare Tunnel stacks** on the same Docker host simultaneously without collisions.

---

## 🎯 Use Case
- You host personal services (`*.personal.me`) and company or client services (`*.company.com`) on the same physical server or VPS.
- Each domain belongs to a different Cloudflare account (or uses a different API token / tunnel).

---

## 🛡️ How Collision Prevention Works

1. **Domain Scoping:**
   `personal-gateway` has `DOMAIN_NAME=personal.me`. It strictly manages containers with hostnames ending in `.personal.me`.
   `business-gateway` has `DOMAIN_NAME=company.com`. It strictly manages containers with hostnames ending in `.company.com`.
   Neither stack touches or overwrites the other stack's DNS records or ingress rules.

2. **Isolated Networks:**
   - Personal services attach to `cf-tunnel-net-personal`.
   - Business services attach to `cf-tunnel-net-business`.

3. **Separate Ports & Volumes:**
   - Each stack runs in its own directory, giving it isolated named volumes (e.g. `personal-gateway_cf_token_data`).
   - The dashboards listen on different host ports (`8080` vs `8081`).
