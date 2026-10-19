# Personal gateway

This is the personal half of the [two-gateway walkthrough](../README.md). It creates `cf-tunnel-net-personal`, targets `personal-cloudflared`, and publishes the companion frontend on host port 8080.

From this directory, copy `.env.example` to `.env` and replace the `example.com` domain, token, and dashboard password. The optional account ID is forwarded when set. Keep the connector name, network, port, and Compose project distinct from the other gateway.

```bash
cp .env.example .env
```

After editing the file privately:

```bash
docker compose up -d
docker compose logs --tail=50 cf-tunnel-sync cloudflared
```

The template binds the frontend to `127.0.0.1`; visit `http://localhost:8080`. The connector waits for its shared token before starting. Follow the [parent guide](../README.md#attach-an-application) to attach a service to the network and scope it to `personal-tunnel`.

Stop this project with `docker compose down` from this directory. This retains the token volume and remote resources. The other gateway has its own project/volume and should remain running.
