"""Hermetic tests ensuring all documentation markdown assets, links, and screenshots exist."""

import re
from pathlib import Path


def get_repo_root() -> Path:
    """Resolve repository root directory."""
    current = Path(__file__).resolve().parent
    # current is cf-tunnel-sync, parent is repo root
    return current.parent


def find_markdown_files(repo_root: Path):
    """Find all markdown files in the repository, excluding virtual environments and git."""
    for md_file in repo_root.rglob("*.md"):
        # Exclude hidden directories and temporary caches
        parts = md_file.parts
        if any(part.startswith(".") or part in ("venv", ".venv", "__pycache__") for part in parts):
            continue
        yield md_file


def extract_relative_references(md_content: str):
    """Extract relative image and file references from markdown content."""
    # Matches ![alt](target) and [text](target), ignoring remote URLs and anchors
    md_link_pattern = re.compile(r"!?\[.*?\]\((?!https?://|mailto:|#|tel:)(.*?)\)")
    # Matches <img ... src="target" ...>, ignoring remote URLs
    html_img_pattern = re.compile(r"""<img[^>]+src=["'](?!https?://|data:)([^"']+)["']""")

    references = []

    for match in md_link_pattern.finditer(md_content):
        raw = match.group(1).split("#")[0].split("?")[0].strip()
        if raw:
            references.append(raw)

    for match in html_img_pattern.finditer(md_content):
        raw = match.group(1).split("#")[0].split("?")[0].strip()
        if raw:
            references.append(raw)

    return references


def test_readme_screenshots_exist_and_valid():
    """Verify that required screenshots referenced in README exist and are valid PNG images."""
    repo_root = get_repo_root()
    expected_screenshots = [
        "docs/screenshots/dashboard-preview.png",
        "docs/screenshots/dashboard-dark.png",
        "docs/screenshots/dashboard-mobile.png",
    ]

    png_magic = b"\x89PNG\r\n\x1a\n"

    for rel_path in expected_screenshots:
        asset_path = repo_root / rel_path
        assert asset_path.exists(), f"Expected screenshot asset missing: {rel_path}"
        assert asset_path.is_file(), f"Asset path is not a file: {rel_path}"

        # Verify file size is substantial (not a stub or 0-byte file)
        file_size = asset_path.stat().st_size
        assert file_size > 10_000, f"Screenshot {rel_path} file size is suspiciously small ({file_size} bytes)"

        # Verify PNG magic header bytes
        with open(asset_path, "rb") as f:
            header = f.read(8)
            assert header == png_magic, f"Asset {rel_path} does not have valid PNG magic bytes"


def test_all_markdown_relative_assets_exist():
    """Verify that every relative image and document link across all markdown files exists on disk."""
    repo_root = get_repo_root()
    broken_references = []
    total_checked = 0

    for md_file in find_markdown_files(repo_root):
        content = md_file.read_text(encoding="utf-8")
        md_dir = md_file.parent
        refs = extract_relative_references(content)

        for ref in refs:
            total_checked += 1
            resolved = (md_dir / ref).resolve()
            if not resolved.exists():
                broken_references.append(
                    f"File '{md_file.relative_to(repo_root)}' references non-existent target '{ref}' (resolved: {resolved})"
                )

    assert total_checked > 0, "Expected at least one relative reference across markdown documentation"
    assert not broken_references, "Found broken relative markdown links/assets:\n" + "\n".join(broken_references)


def test_dockerhub_markdown_files_exist_and_consistent():
    """Verify that Docker Hub documentation files exist, are non-empty, and align with core configuration."""
    repo_root = get_repo_root()
    dashboard_hub = repo_root / "cf-tunnel-dashboard" / "DOCKERHUB.md"
    sync_hub = repo_root / "cf-tunnel-sync" / "DOCKERHUB.md"

    assert dashboard_hub.exists(), "cf-tunnel-dashboard/DOCKERHUB.md missing"
    assert sync_hub.exists(), "cf-tunnel-sync/DOCKERHUB.md missing"

    dashboard_content = dashboard_hub.read_text(encoding="utf-8")
    sync_content = sync_hub.read_text(encoding="utf-8")

    assert len(dashboard_content) > 500, "cf-tunnel-dashboard/DOCKERHUB.md content too short"
    assert len(sync_content) > 500, "cf-tunnel-sync/DOCKERHUB.md content too short"

    # Verify critical configuration terms are present
    assert "DASHBOARD_AUTH_ENABLED" in dashboard_content
    assert "BASIC_AUTH_USERNAME" in dashboard_content
    assert "BASIC_AUTH_PASSWORD" in dashboard_content
    assert "hapheus/cf-tunnel-dashboard" in dashboard_content

    assert "CLOUDFLARE_API_TOKEN" in sync_content
    assert "CLOUDFLARE_TUNNEL_NAME" in sync_content
    assert "cf.tunnel.enable" in sync_content
    assert "hapheus/cf-tunnel-sync" in sync_content
    assert "QUICKSTART.md" in sync_content
    assert "PREFLIGHT_ONLY" in sync_content
    assert "MAX_DELETIONS_PER_SYNC" in sync_content
    assert "ALLOW_MASS_DELETIONS" in sync_content
    assert "NOTIFICATION_WEBHOOK_URL" in sync_content
    assert "LOG_FORMAT" in sync_content


def test_markdown_asset_scanner_detects_broken_link(tmp_path):
    """Hermetic unit test: ensure scanner properly identifies non-existent files."""
    dummy_md = tmp_path / "TEST.md"
    dummy_md.write_text(
        "# Header\n\n![Missing Image](assets/does_not_exist.png)\n[Valid Self](TEST.md)",
        encoding="utf-8",
    )

    refs = extract_relative_references(dummy_md.read_text(encoding="utf-8"))
    assert "assets/does_not_exist.png" in refs
    assert "TEST.md" in refs

    missing = []
    for ref in refs:
        if not (dummy_md.parent / ref).resolve().exists():
            missing.append(ref)

    assert missing == ["assets/does_not_exist.png"]
