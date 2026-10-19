# Business gateway

This is the second half of the [two-gateway walkthrough](../README.md). It creates `cf-tunnel-net-business`, targets `business-cloudflared`, and publishes the companion frontend on host port 8081.

From this directory, copy `.env.example` to `.env` and replace the `example.net` domain, token, and dashboard password with the second account's values. The optional account ID is forwarded when set. Keep the connector name, network, port, and Compose project distinct from the personal gateway.

```bash
cp .env.example .env
```

After editing the file privately:

```bash
docker compose up -d
docker compose logs --tail=50 cf-tunnel-sync cloudflared
```

The template binds the frontend to `127.0.0.1`; visit `http://localhost:8081`. The connector waits for its shared token before starting. Follow the [parent guide](../README.md#attach-an-application), substituting this gateway's domain, network, and `company-tunnel` name.

Stop this project with `docker compose down` from this directory. This retains the token volume and remote resources. The personal gateway has its own project/volume and should remain running.
