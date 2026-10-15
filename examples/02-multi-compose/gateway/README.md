# Central Gateway Stack

This stack runs the `cloudflared` tunnel agent and the `cf-tunnel-sync` controller. It establishes the bridge network `cf-tunnel-net` that all other application stacks join.

---

## 🚀 How to Run

1. **Configure environment:**
   ```bash
   cp .env.example .env
   # Set DOMAIN_NAME and CLOUDFLARE_API_TOKEN
   ```

2. **Start the gateway:**
   ```bash
   docker compose up -d
   ```

3. **Check status:**
   Open the dashboard at `http://<host-ip>:8080`.
