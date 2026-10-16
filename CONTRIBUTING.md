# Contributing to cf-docker-tunnel-sync

Thank you for your interest in contributing to `cf-docker-tunnel-sync`!

## Development Environment Setup

We recommend using [`uv`](https://docs.astral.sh/uv/) for fast, reproducible Python environment management.

### 1. Clone the repository
```bash
git clone https://github.com/hapheus/cf-docker-tunnel-sync.git
cd cf-docker-tunnel-sync
```

### 2. Install dependencies
```bash
uv sync --extra dev
```

### 3. Run the test suite
```bash
uv run pytest
```

### 4. Code quality & linting
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

3. **Pull Request Workflow:**
   - All contributions must be submitted via Pull Requests against the `main` branch. Direct pushes to `main` are disabled.
   - All GitHub Actions workflows (`ruff` linting, hermetic unit tests, and live container smoke tests) must pass 100% green before any PR can be merged.

4. **Zero Internal AI Files:**
   - Never commit or publish AI planning documents, scratchpads, prompt logs, or temporary markdown artifacts into the repository. Only production code, official documentation, and automated tests belong in version control.
