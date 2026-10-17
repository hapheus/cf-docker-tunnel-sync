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
   - **CLI / Logs:** View background sync events via `docker compose logs -f cf-tunnel-sync`.
   - **Optional Dashboard:** Open the companion web UI at `http://<host-ip>:8080` (or comment out `cf-tunnel-dashboard` in `docker-compose.yml` for pure headless operation).
