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
devenv shell -- uv run pytest cf-tunnel-sync/test_markdown_assets.py
devenv shell -- uv run pytest
devenv shell -- uv run ruff check .
```

Use isolated fixtures and mocked APIs for local checks. A mock passing does not establish live Docker/Cloudflare behavior. Access to a running Docker daemon or authenticated services requires task-specific authorization. Required CI checks must pass before merge regardless of the agreed local subset.

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
