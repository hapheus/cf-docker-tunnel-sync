# Create a scoped Cloudflare API token

The synchronizer needs access to one Cloudflare account and the zone named by `DOMAIN_NAME`. Use a custom API token scoped to those resources rather than the Global API Key.

## Permissions

| Scope | Resource | Permission | Used for |
| --- | --- | --- | --- |
| Account | Cloudflare Tunnel | Edit | Find/create a remotely managed tunnel, retrieve its token, and update ingress. |
| Zone | DNS | Edit | Read and manage service CNAME records. |
| Zone | Zone | Read | Look up the zone and its account. |

Cloudflare's [API tunnel setup guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel-api/) describes tunnel/DNS provisioning. This project additionally resolves the zone by name.

## Create the token

1. Open Cloudflare's API token settings and choose a custom token. See [Create API token](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/) for current navigation.
2. Add the permissions above.
3. Restrict account resources to the intended account and zone resources to the intended zone. Broader scopes are unnecessary for a single gateway.
4. Create the token and store it securely; do not include it in screenshots or support requests.
5. Pass it into the container as `CLOUDFLARE_API_TOKEN`, along with `DOMAIN_NAME` and the intended `CLOUDFLARE_TUNNEL_NAME`.

![Example token permission setup](screenshots/cloudflare-token-setup.png)

The screenshot is illustrative; dashboard labels/layout may change. Use the permission names and resource scope rather than matching every visual detail.

## Verify access

Once the sync container is available with its environment configured:

```bash
docker compose exec cf-tunnel-sync python app.py --preflight
```

Preflight performs read-only Docker and Cloudflare requests. It checks token activity and attempts zone/tunnel inspection. Token activity alone does not prove all required permissions, and preflight does not exercise DNS mutations. A missing tunnel is reported as a preflight failure even though normal startup can create one.

Normal synchronization can create a tunnel and modify routes/DNS. Dry-run prevents these writes, including initialization. Read [current safety limitations](architecture-and-safety.md#current-limitations) before using an existing setup.
