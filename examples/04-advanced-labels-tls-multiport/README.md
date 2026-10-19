# Origin TLS, headers, and multiple ports

This example runs two HTTPS whoami origins and one Nginx origin listening on ports 80 and 8080. You need Docker Compose v2, local OpenSSL with `-addext` support, a Cloudflare zone, and a [scoped token](../../docs/cloudflare-permissions.md).

## Prepare a demonstration certificate

From this directory:

```bash
cp .env.example .env
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
  -keyout certs/origin.key -out certs/origin.crt \
  -subj '/CN=origin.internal' \
  -addext 'subjectAltName=DNS:origin.internal'
```

The certificate and unencrypted private key are local demonstration material under Git-ignored `certs/`. Both HTTPS containers mount that directory read-only. Do not commit the key. Certificate generation overwrites these filenames; reuse existing files if you do not intend to replace them.

The whoami image accepts certificate, key, and port arguments; see its [upstream usage](https://github.com/traefik/whoami#flags). These services actually start TLS listeners on 8443 rather than merely labeling an HTTP server as HTTPS.

## Configure and start

Edit `.env` with your token, domain, and dedicated tunnel name, then:

```bash
docker compose up -d
docker compose logs --tail=50 cf-tunnel-sync cloudflared
```

The connector waits for a nonempty token and the sync health endpoint. No application host ports are published. Inspect [current safety limitations](../../docs/architecture-and-safety.md#current-limitations) before using existing Cloudflare resources.

## Scenario A: Self-signed HTTPS

`app-selfsigned-https` starts whoami with `--port=8443`, `--cert`, and `--key`. The explicit service URL points at that HTTPS listener. `cf.tunnel.originRequest.noTLSVerify=true` allows the self-signed certificate; it does not configure user authentication.

```bash
curl -I https://tls-app.example.com
```

Replace the domain. The public URL uses Cloudflare's edge certificate; `noTLSVerify` applies to the connector-to-origin connection.

## Scenario B: Host header and server name

`app-custom-headers` also listens on HTTPS 8443. Its labels set `cf.tunnel.httpHostHeader=cloud.<your-domain>` and `cf.tunnel.originServerName=origin.internal`.

```bash
curl https://cloud.example.com
```

The whoami response should show `Host: cloud.<your-domain>`. The server-name label is forwarded as an origin TLS option; the response does not prove SNI or certificate verification. Verification is disabled for this self-signed demonstration. For production, use a certificate trusted by the connector and enable verification.

## Scenario C: Explicit port selection

The mounted [multiport.conf](multiport.conf) makes Nginx listen on both 80 and 8080. Its explicit `cf.tunnel.port=8080` selects the second listener.

```bash
curl https://multiport.example.com
```

Expected body: `Origin listening port: 8080`. This demonstrates routing to a non-default port. Without an explicit label, current discovery uses the first Docker `PrivatePort` entry, not a guaranteed multi-port disambiguation algorithm.

## Stop and clean up

```bash
docker compose down
```

Volumes, certificate files, and remote Cloudflare resources remain. Remove local demonstration keys only when no container uses them; follow [operations](../../docs/operations.md) for remote cleanup. See [labels](../../docs/labels.md) for the exact current spellings and precedence.
