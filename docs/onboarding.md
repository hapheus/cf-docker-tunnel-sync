# Expose an existing Docker service

This guide assumes the gateway and `cloudflared` are already running and share a Docker network named `cf-tunnel-net`. For a first installation, start with the [Quickstart](../QUICKSTART.md) or the [separate-stack walkthrough](../examples/02-multi-stack-external-net/README.md).

You need a hostname in the configured Cloudflare zone and the port your application listens on inside its container. Read the [current safety limitations](architecture-and-safety.md#current-limitations) before attaching existing Cloudflare resources.

## Connect the service

For an HTTP service listening on port 8080, adapt its Compose definition:

```yaml
services:
  my-app:
    image: your-application-image:your-version
    restart: unless-stopped
    networks:
      - default
      - cf-tunnel-net
    labels:
      cf.tunnel.hostname: app.example.com
      cf.tunnel.port: "8080"

networks:
  cf-tunnel-net:
    external: true
```

Replace the image, hostname, and port. Keep the service's existing configuration and networks. The external network must already exist; start the gateway before the application stack.

No host `ports` mapping is required for tunnel traffic. Keep one if you also need deliberate direct LAN access.

Apply the changes from the application's Compose directory:

```bash
docker compose up -d my-app
```

Changing labels or networks requires container recreation. A plain restart does not apply those changes.

## Verify routing

From the gateway directory, inspect both services:

```bash
docker compose logs --tail=50 cf-tunnel-sync cloudflared
```

Look for the hostname in discovery and for ingress/DNS errors. The [status API](api.md) also reports discovered services and diagnostic stages.

From a client with network access to the public hostname:

```bash
curl -I https://app.example.com
```

Expect the application's normal response, such as 200, a redirect, or an authentication challenge. An HTTP response alone does not prove the intended access policy is enforced; verify authorization separately.

For connection errors, see [troubleshooting](troubleshooting.md).

## HTTPS origins

If the application serves HTTPS inside Docker, set the protocol as well as the port:

```yaml
labels:
  cf.tunnel.hostname: app.example.com
  cf.tunnel.port: "8443"
  cf.tunnel.protocol: https
  cf.tunnel.originRequest.noTLSVerify: "true"
```

The last label skips certificate verification for self-signed origins. Prefer verified certificates where possible. See [origin TLS settings](labels.md#https-origins) for server-name and Host-header overrides.

## Multiple gateways and private applications

Set `cf.tunnel.name` to the desired gateway's tunnel name when more than one synchronizer can discover the container.

For private applications, configure application authentication or Cloudflare Access separately. An Access label is only metadata and does not secure the route. See [security](security.md#public-applications-and-access-metadata).
