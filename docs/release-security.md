# Container releases and image identity

The repository builds separate sync and companion-dashboard images. Use a specific published version or digest when you need repeatable deployments; `latest` can change.

## Image tags and digests

The [publish workflow](../.github/workflows/docker-publish.yml) builds on pushes to `main`, version tags matching `v*.*.*`, and manual invocation. Its metadata rules produce branch tags, a full semantic-version tag for a version-tag event, and `latest` on `main`.

Do not assume minor/major tags exist or that registry tags are immutable. A digest identifies the image content more precisely than a tag. For an available release, replace these placeholders in your Compose service:

```yaml
image: hapheus/cf-tunnel-sync:<published-version>
```

Or pin a verified manifest digest:

```yaml
image: hapheus/cf-tunnel-sync@sha256:<verified-manifest-digest>
```

Keep the old reference for rollback. See [upgrade and rollback](COMPATIBILITY.md).

## Build properties

The sync [Dockerfile](../cf-tunnel-sync/Dockerfile) uses a digest-pinned Python 3.11 Alpine base and installs production dependencies deterministically from `uv.lock` using `uv sync --frozen --no-dev`. Consequently, rebuilding identical source reproduces identical dependency resolution across local development, CI, and production container builds.

The sync image does not declare a non-root `USER`. The connector token directory must be writable. Do not infer non-root execution, a universally read-only filesystem setup, or reproducible dependencies from the multi-stage build alone.

The publish workflow targets `linux/amd64` and `linux/arm64`. Publication of a particular artifact and its registry metadata must be checked for that release; local YAML inspection does not prove successful publication.

## Signatures and dependency inspection

The workflow contains keyless Cosign signing of the published digest. Verify the artifact you deploy using your expected repository/workflow identity and trusted issuer; the presence of a signing step alone does not establish a valid signature for every historical image.

The workflow does not explicitly request SBOM generation. Build tooling may attach provenance/attestations depending on its defaults; inspect the actual release rather than promising a specific SBOM or provenance format.

If you have a scanner installed, you can inspect an image independently, for example:

```bash
syft hapheus/cf-tunnel-sync:<published-version> -o spdx-json
trivy image hapheus/cf-tunnel-sync:<published-version>
```

These commands contact a registry and use external tools. Generating a local inventory is not the same as verifying a publisher-supplied attestation, and a clean scan is not a guarantee of application security.
