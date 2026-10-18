---
name: Bug Report
about: Create a report to help us improve cf-docker-tunnel-sync
title: "fix: [brief description of problem]"
labels: ["bug"]
assignees: ''
---

## 🐛 Bug Description
A clear and concise description of what the bug is.

## 📋 Environment Details
- **cf-docker-tunnel-sync Version / Image Tag:** (e.g. `v1.19.0` or `latest`)
- **Docker Engine Version:** (e.g. `24.0.7`)
- **Docker Compose Version:** (e.g. `v2.24.1`)
- **Operating System & Architecture:** (e.g. `Ubuntu 22.04 LTS (x86_64)` or `Debian Bookworm (arm64)`)
- **Deployment Mode:** (Single Compose / Multi-Compose Gateway / Standalone Dashboard)

## 🐳 Minimal Reproducible Docker Compose Stack
```yaml
# Please paste your sanitized compose file below (omit secrets):
services:
  app:
    image: nginx:alpine
    networks:
      - cf-tunnel-net
    labels:
      - "cf.tunnel.hostname=test.example.com"
      - "cf.tunnel.port=80"
```

## 📜 Log Output (Ensure Sensitive Tokens are Redacted)
```text
# Paste output from: docker logs cf-tunnel-sync --tail 50
# Ensure API tokens, passwords, and sensitive URLs are replaced with [REDACTED]
```

## 🔄 Steps to Reproduce
1. Start stack with `docker compose up -d`
2. Run diagnostic preflight: `docker exec cf-tunnel-sync python app.py --preflight`
3. Observe error output...

## 🎯 Expected vs. Actual Behavior
- **Expected:** (e.g. Ingress rule updated and DNS CNAME created)
- **Actual:** (e.g. 502 Bad Gateway or sync error)
