# Service: Whoami Debugger

A tiny debugging web service that prints incoming HTTP request headers and IP details.

---

## 🚀 How to Run

1. **Ensure the central gateway is running:**
   Make sure `examples/02-multi-compose/gateway` is up and the `cf-tunnel-net` network exists.

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
   Open `https://whoami.<yourdomain.com>`.
