# Service: HTTP API / Httpbin

An HTTP API backend service (using httpbin) demonstrating API endpoint exposure through the central tunnel gateway.

---

## 🚀 How to Run

1. **Ensure the central gateway is running:**
   Verify `cf-tunnel-net` is active.

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Set DOMAIN_NAME=yourdomain.com
   ```

3. **Start the service:**
   ```bash
   docker compose up -d
   ```

4. **Access your service:**
   Open `https://api.<yourdomain.com>/get` to test JSON responses.
