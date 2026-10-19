# Container labels

The synchronizer reads running containers and selects a normalized hostname within `DOMAIN_NAME`. Use one fully qualified hostname per container and set its internal port explicitly.

```yaml
services:
  web:
    image: nginx:alpine
    networks:
      - cf-tunnel-net
    labels:
      cf.tunnel.hostname: web.example.com
      cf.tunnel.port: "80"

networks:
  cf-tunnel-net:
    external: true
```

Run this application stack after creating the gateway network. Host port publication is not needed for tunnel traffic.

## Routing labels

| Label | Default | Effect |
| --- | --- | --- |
| `cf.tunnel.hostname` | Required for selection | One hostname, such as `web.example.com`. The hostname must belong to the configured zone. |
| `cf.tunnel.port` | Docker metadata, then protocol default | Container's internal listening port, from `1` to `65535`. |
| `cf.tunnel.protocol` | `http` | Origin scheme. Also reads `cf.tunnel.proto` and `cf.tunnel.scheme`, in that order. Parsed schemes include `http`, `https`, `tcp`, `udp`, `ssh`, and `rdp`; parser acceptance does not establish end-to-end support for each Cloudflare protocol. |
| `cf.tunnel.service` | Constructed origin URL | Explicit origin URL; overrides port/name construction. |
| `cf.tunnel.name` | Unscoped | Selects this container only when the value matches `CLOUDFLARE_TUNNEL_NAME`; also reads `cf.tunnel.tunnel`. |
| `cf.tunnel.access.policy` | `unspecified` | Lowercased metadata shown in status. Also reads `cf.tunnel.access_policy`. **Does not create or enforce Cloudflare Access policies.** |

Containers without a tunnel-name restriction are eligible for every instance managing their domain. Set `cf.tunnel.name` when using multiple gateways.

### Hostname and selection details

The parser lowercases hostnames, removes trailing dots and URL components, and validates DNS labels. Prefer a plain fully qualified hostname. It does not expand a short name such as `web` into `web.example.com`, or split comma-/space-separated names into multiple routes. When multiple containers request the same hostname, the first discovered one wins.

`cf.tunnel.enable` is not checked by current discovery. Its absence does not disable discovery, and setting it to `false` does not opt out. Remove the hostname labels or use tunnel scoping to stop matching this synchronizer.

`cf.tunnel.path` is not consumed by the normal discovery/planning pipeline. Do not use it to configure path-based routes. Existing manual path rules also have preservation limitations; see [architecture and safety](architecture-and-safety.md#current-limitations).

### Port selection

The current discovery order is:

1. A valid explicit port label, unless an explicit service URL overrides construction.
2. The first valid `PrivatePort` entry in the Docker container-list response.
3. `443` for an HTTPS origin, or `80` for other schemes.

This is not a single-EXPOSE-only algorithm. Invalid port labels can fall back to metadata/defaults. Set the correct port explicitly for predictable routing; image metadata does not prove that the application is listening there.

## HTTPS origins

Use HTTPS as the origin protocol when the application itself serves TLS:

```yaml
labels:
  cf.tunnel.hostname: vault.example.com
  cf.tunnel.port: "8443"
  cf.tunnel.protocol: https
  cf.tunnel.originRequest.noTLSVerify: "true"
```

Disabling verification accepts an unverified origin certificate. Prefer a valid certificate where practical.

| Label to use | Effect |
| --- | --- |
| `cf.tunnel.originRequest.noTLSVerify` | Disables origin certificate verification for `true`, `1`, or `yes`; accepts `false`, `0`, and `no`. Also reads `cf.tunnel.notlsverify`, `cf.tunnel.notls_verify`, and `cf.tunnel.origin_request.no_tls_verify`. |
| `cf.tunnel.originServerName` | Sets origin TLS server name; also reads `cf.tunnel.origin.server.name` and `cf.tunnel.origin_server_name`. |
| `cf.tunnel.httpHostHeader` | Overrides the HTTP Host header; also reads `cf.tunnel.http.host.header` and `cf.tunnel.http_host_header`. |

The current normal parser does not read `cf.tunnel.originRequest.originServerName` or `cf.tunnel.originRequest.httpHostHeader`, despite their appearance in older references. Use the spellings in the table.

## Legacy labels and precedence

For new deployments, use the labels above. Current discovery also reads:

- Hostname: `cf.tunnel.domain`, `cf.tunnel.host`, `cloudflared.hostname`, `cloudflared.domain`, `cloudflared.host`, `hostname`, `host`, after `cf.tunnel.hostname`, in that order.
- Port: `cloudflared.port`, then `port`, after `cf.tunnel.port`.
- Protocol: the `cloudflared.protocol`, `cloudflared.proto`, `cloudflared.scheme` variants, then `proto`, `protocol`, `scheme`, after the three modern variants.
- Service: `cloudflared.service`, after `cf.tunnel.service`.
- Tunnel name: `cloudflared.name`, then `cloudflared.tunnel`, after the modern variants.
- Access metadata: `cloudflared.access.policy`, after the modern variants.

TLS handling prefers modern no-verification labels, modern verification labels (`cf.tunnel.tls.verify` / `cf.tunnel.tls_verify`), legacy equivalents, then shorthand `notlsverify`, `no_tls_verify`, and `tls_verify`. Avoid conflicting aliases.

The separate configuration alias registry lists additional names, including `tunnel.*` and `cftunnel.*`. Normal discovery does not resolve that registry, so do not rely on those names to route a service. Existing aliases are not being removed by this documentation update; the distinction is between registered names and actual parser behavior.
