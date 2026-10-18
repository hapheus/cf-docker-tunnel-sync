# Contributing to cf-docker-tunnel-sync

Thank you for your interest in contributing to `cf-docker-tunnel-sync`!

## Development Environment Setup

You can set up your development environment using either [`devenv`](https://devenv.sh/) with [`direnv`](https://direnv.net/) for instant hermetic isolation, or directly using [`uv`](https://docs.astral.sh/uv/).

### Option A: Using devenv & direnv (Recommended for Nix users)

If you have `direnv` and `devenv` installed:
```bash
# Allow direnv to load the shell automatically
direnv allow
```
This automatically provisions Python 3.11, installs `uv`, `ruff`, and enables Git pre-commit hooks for code formatting.

### Option B: Using uv (Fast, Cross-Platform)

```bash
# 1. Clone the repository
git clone https://github.com/hapheus/cf-docker-tunnel-sync.git
cd cf-docker-tunnel-sync

# 2. Install dependencies and dev tools
uv sync --extra dev
```

## Running Tests

Run the hermetic test suite (including unit tests, wire-level mocks, and Compose schema validation):
```bash
uv run pytest -v
```

## Code Quality & Linting

We use [`ruff`](https://docs.astral.sh/ruff/) for linting and code formatting:
```bash
# Check code style and linting
uv run ruff check

# Automatically fix lint issues where possible
uv run ruff check --fix

# Format code
uv run ruff format
```

## Contribution Guidelines

1. **GitHub Issues for Everything:**
   - Every bug fix, feature, enhancement, or documentation update must map to an open GitHub Issue.
   - Started issues should be assigned before implementation begins.

2. **Language Policy:**
   - All code, comments, documentation, commit messages, issue discussions, and pull requests must be strictly in **English**.

3. **Pull Request Workflow & Branch Protection:**
   - Direct pushes to `main` are protected via GitHub Rulesets.
   - All contributions must be submitted via Pull Requests against the `main` branch.
   - All GitHub Actions workflows (`ruff` linting, hermetic unit tests, and live container smoke tests) must pass 100% green before any PR can be merged.

4. **Documentation & Asset Integrity:**
   - Any images, screenshots, or diagrams referenced in documentation (such as in README.md or examples/) must reside in docs/screenshots/ or docs/assets/ and be committed alongside documentation changes.
   - Hermetic test suites automatically validate that all relative links, images, and document references exist on disk.

5. **Scope Policy & Non-Goals:**
   - Review [docs/product-boundaries.md](docs/product-boundaries.md) before submitting non-trivial PRs.
   - Resist out-of-scope abstractions, third-party DNS synchronizers, or generic LAN proxying.

6. **Redacted Logs Guidance:**
   - When filing issues or posting terminal outputs, always redact Cloudflare API tokens, passwords, and webhook URLs (`[REDACTED]`).
   - The sync engine includes automatic runtime redaction for logs and audit events.

7. **Contributor PR Checklist:**
   - [ ] Local tests pass cleanly: `uv run pytest`
   - [ ] Linter & formatter clean: `uv run ruff check . && uv run ruff format .`
   - [ ] Conventional Commit messages (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`)
   - [ ] Linked GitHub issue (`Fixes #123`)
   - [ ] Strictly zero breaking changes to existing environment variables, labels, or compose files

