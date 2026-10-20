# Contributing

Keep changes focused on running Docker/Compose services behind Cloudflare Tunnel. See [product scope](docs/product-boundaries.md) before proposing new providers, orchestration platforms, databases, Access-policy management, or a substantial architecture change.

## Development environment

Use devenv with its managed Python virtual environment and direnv:

```bash
direnv allow
```

The repository's `.envrc` loads devenv. Python dependencies and development tools are managed by the project; do not install them into system Python. To invoke a command explicitly through the environment, use `devenv shell -- uv run <command>`.

## Verification

Agree the check scope for each task before running it. Choose checks that address the changed behavior. Available commands include:

```bash
devenv shell -- uv run pytest tests/docs/test_markdown_assets.py
devenv shell -- uv run pytest
devenv shell -- uv run ruff check .
devenv shell -- uv run mypy --follow-imports=silent src/tunnel_sync
```

Use isolated fixtures and mocked APIs for local checks. A mock passing does not establish live Docker/Cloudflare behavior. Access to a running Docker daemon or authenticated services requires task-specific authorization. Required CI checks must pass before merge regardless of the agreed local subset.

The application is installable as a Python package. Build distributions with `devenv shell -- uv build`; the wheel contains the `tunnel_sync` components, compatible top-level modules, and dashboard assets. The container continues installing production dependencies from `uv.lock` and copying application source. Export the dependency-only requirements with `uv export --no-dev --no-emit-project --frozen -o cf-tunnel-sync/requirements.txt` so the editable application itself does not enter that list.

## Python architecture

See [component boundaries](docs/architecture-and-safety.md#python-component-boundaries). Keep planner inputs explicit and transformation functions free of environment reads, clocks, random IDs, and provider calls. Keep Cloudflare writes, token writes, and connector activation in `ChangeExecutor`. Construct applications with `tunnel_sync.web.app.create_app(settings, services)` and services with `tunnel_sync.bootstrap.create_services(settings, ...)`.

`tests/integration/` constructs independent compositions with stateful Docker/Cloudflare fakes from `tests/fakes.py`. It covers convergence, drift, partial failure, tombstone retries, application independence, status reads during provider I/O, and shutdown ownership. `tests/architecture/` checks dependency direction and import side effects. `tests/conftest.py` adapts older tests that patch historical `app` helpers; those adaptations do not run in production.

Keep new tests at the service or pure-function boundary. Retain historical contract fixtures when verifying configuration, labels, HTTP schemas, authentication, and metrics. Production behavior must not depend on detecting a mock or omitting ownership metadata from a fixture.

## Language and documentation

Use English throughout code, comments, documentation, commit messages, issues, PRs, reviews, and release notes. Write factually and accessibly for homelab operators with Docker Compose basics.

`docs/` is human-facing documentation: setup, configuration, operation, troubleshooting, integration, and architecture explanations. Keep agent instructions and implementation work plans outside it. Document current behavior, including limitations, rather than intended features or unconditional safety guarantees.

Keep one reference per topic and link to it. Include local screenshots under `docs/screenshots/`. Verify relative links, examples, and expected output when changing related behavior. An environment-variable registry entry alone does not prove runtime support.

## Changes and review

Use a work branch; do not implement changes on `main` or push directly to it. Local work does not require an issue. Link an issue when one exists. Use Conventional Commit messages and describe the problem, resulting behavior, and validation in the PR.

Preserve existing configurations, labels, and API contracts. Explain necessary security corrections and discuss unavoidable larger compatibility changes before implementing them. Keep broad refactors separate from documentation corrections.

For agent-assisted work, local editing does not authorize commits, pushes, or PR creation; obtain the user's approval first. Review/merge authorization and account roles follow the project's local agent instructions. Do not bypass required checks or branch protection.

Every merge to `main`, including documentation-only changes, requires a matching version tag and GitHub Release. Documentation-only releases increment the patch version. Prefer release automation, but confirm it exists and has completed rather than assuming a merge creates a release. Publication and automation changes require their own authorization.

## Sharing diagnostics

Review and redact logs before posting them. Do not include `.env` content, API tokens, connector tokens, passwords, or webhook secrets. Use dummy credentials in tests and examples.
