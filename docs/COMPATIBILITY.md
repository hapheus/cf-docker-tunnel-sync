# Upgrade and rollback

Keep existing configuration, labels, and API integrations when upgrading. Compatibility is a project goal, but test coverage and a stateless controller do not guarantee every upgrade or downgrade is harmless. Review the target release and the current [safety limitations](architecture-and-safety.md#current-limitations).

## Before upgrading

Record the running image digest or exact version and save your Compose/environment configuration securely. Keep secrets out of version control and support reports. For a tunnel with manual rules, retain a copy of the relevant remote ingress/DNS configuration as well.

The repository contains fixture tests for single-stack, separate-stack, socket-proxy, and scoped-gateway configurations. These checks do not establish compatibility with every Docker version, host platform, legacy alias, or custom remote configuration. See [support](support-matrix.md) and the actual [configuration](configuration.md) and [label](labels.md) references.

## Upgrade

From the gateway directory:

1. Set the desired image version or digest in Compose. Check [image identity](release-security.md) rather than relying on a floating `latest` tag.
2. Pull and recreate the affected service:

   ```bash
   docker compose pull cf-tunnel-sync
   docker compose up -d cf-tunnel-sync
   ```

3. Inspect initialization and status:

   ```bash
   docker compose logs --tail=100 cf-tunnel-sync cloudflared
   curl --fail-with-body http://localhost:8080/health
   curl --fail-with-body --user admin http://localhost:8080/api/status
   ```

   Adjust host port/user for your deployment. Health alone does not prove synchronization or public reachability.

4. Check representative public applications, intended authentication, and unexpected route/DNS changes.

A fresh process can rewrite ingress even without a desired-state change. Do not treat zero API writes as a universal upgrade guarantee.

## Roll back

Restore the previously recorded image version/digest and compatible Compose settings, then pull/recreate the service and repeat the verification above. Check that settings introduced by the newer version do not depend on behavior absent from the older version.

The synchronizer has no local database migrations to reverse. However, a previous version can interpret labels or remote configuration differently; recreating the old container does not undo Cloudflare changes already made. Review the remote state if the failed upgrade changed it.

The token volume persists across ordinary service recreation. In-memory tombstones/history/caches reset. Do not delete volumes as a routine rollback step.
