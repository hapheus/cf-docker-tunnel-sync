# Cloudflare Tunnel Docker synchronizer

`hapheus/cf-tunnel-sync` reads Docker labels and manages Cloudflare Tunnel ingress and CNAME records. Run it alongside `cloudflared`, which carries application traffic. The embedded dashboard is optional; headless deployments still run the internal API without publishing a host port.

Follow the complete [QUICKSTART.md](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/QUICKSTART.md) for the gateway Compose file. Both services must mount the same token volume at `/etc/cloudflared`; the connector runs with `--token-file /etc/cloudflared/token`. Do not supply a manually copied connector token as a substitute for that setup.

## Application labels

Attach your service to the connector's Docker network and use a single fully qualified hostname and explicit internal port:

```yaml
labels:
  cf.tunnel.hostname: app.example.com
  cf.tunnel.port: "8080"
```

Current discovery does not use `cf.tunnel.enable` to opt in or out. Path labels are not wired into normal routing, and Access labels are metadata rather than access controls. Use the maintained [label reference](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/labels.md) for actual spellings and behavior.

## Configuration

Set `CLOUDFLARE_API_TOKEN`, `DOMAIN_NAME`, and a dedicated `CLOUDFLARE_TUNNEL_NAME`. Account selection is normally derived from the zone. The fallback sync interval is 900 seconds; Docker events trigger earlier runs.

`MAX_DELETIONS_PER_SYNC` defaults to three and `ALLOW_MASS_DELETIONS` overrides execution deletion limits. `LOG_FORMAT=json` enables structured logs; `NOTIFICATION_WEBHOOK_URL` enables alert delivery. Pass these into the container explicitly; a Compose `.env` entry alone is not automatically injected.

For read-only inspection, run `python app.py --preflight` or set `PREFLIGHT_ONLY=true`. It reads configured Docker and Cloudflare resources and exits. In contrast, `DRY_RUN=true` skips ingress/DNS execution only after initialization: a missing tunnel can still be created, its token written, and the connector restarted.

The [configuration reference](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/configuration.md) distinguishes active settings from names only recognized by validation or other entry points.

## Status and safety

The internal HTTP port is 8090. Keep it private unless deliberately publishing it with authentication. The embedded dashboard and optional [`hapheus/cf-tunnel-dashboard`](https://hub.docker.com/r/hapheus/cf-tunnel-dashboard) use the documented API.

Use a scoped Cloudflare token and treat Docker socket access as privileged even with a `:ro` mount. Manual ingress rules and absent DNS ownership fields have [known safety limitations](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/architecture-and-safety.md#current-limitations). Use a dedicated tunnel rather than assuming existing routing is preserved losslessly.

[Documentation](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/README.md) · [Operations](https://github.com/hapheus/cf-docker-tunnel-sync/blob/main/docs/operations.md) · [Source and issues](https://github.com/hapheus/cf-docker-tunnel-sync)
