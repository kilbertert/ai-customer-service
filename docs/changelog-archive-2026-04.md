# Changelog 历史归档（2026-04-16 及之前）

> 本文件是**归档**，不是现行的变更日志。现行的 `CHANGELOG.md` 由 `dev-changelog`
> 从 Conventional Commits 生成，覆盖仓库的全部历史。
>
> 这份内容写于 2026-04-16，由人阅读代码与部署脚本后提炼，描述**当时**的变更。
> 它无法由生成器重建：那一批提交的主题是 `Finish scheduler shutdown symmetry and
> secret handling cleanup.` 这类自由格式文本，正文里也没有提到本文件所述的细节
> （已核实：`SSRF` / `cors_allow_null_origin` / `ENCRYPTION_KEY` / `REQUIRE_SECRET_KEY`
> 在 2026-04-17 之前的提交主题与正文中出现 0 次）。因此本文件是这批信息在仓库中的
> 唯一留存，保留原文不动。

---

All notable changes to this project should be documented in this file.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- One-command production installer/deployer (`install-deploy.sh`): auto-installs Docker/Compose, clones/syncs repository, deploys production profile via `deploy.sh`, and verifies container health checks.
- `deploy.sh` now supports `BASJOO_DOCKER_BIN` environment variable for custom Docker binary invocation (e.g., `sudo docker`).
- SSRF protection for URL ingestion (`backend/services/url_safety.py`): blocks localhost, direct IP literals, embedded credentials, and hostnames resolving to private/special-use IPs.
- Admin authentication at the router level for URL/Q&A management (`url_endpoints.py`) and index rebuild (`index_endpoints.py`) endpoints.
- `cors_allow_null_origin` config flag (default `false`) for explicit `file://` widget preview support in dev environments.
- `ENCRYPTION_KEY` / `ENCRYPTION_KEY_FILE` for Fernet-based API key encryption at rest (`core/encryption.py`).
- `REQUIRE_SECRET_KEY` environment variable to reject insecure secret keys in production.
- Key rotation support for Jina embedding client.
- E2E test workflow with Playwright: smoke, prod-like, and widget cross-origin test projects.

### Changed

- CORS policy tightened: missing `Origin` headers no longer receive wildcard CORS; `Origin: null` only allowed when `cors_allow_null_origin` is explicitly enabled.
- Early-response CORS handling unified through a single shared helper (`apply_cors_headers` in `backend/middleware/rate_limit.py`).
- URL validation in schemas replaced with the shared SSRF safety check, removing localhost and direct IP acceptance.
- Scheduler shutdown lifecycle made symmetric; secret handling and login fallback limiter tightened.
- Health endpoint behavior unified across request paths.
- Chat rate limits operate on per-minute sliding windows.
- URL normalization improved for repeated query parameters.
- URL fetch/crawl quota paths and training-state synchronization tightened.

### Fixed

- In-memory sliding window rate limiter now evicts stale keys to prevent unbounded map growth.
- Widget XSS gap in source rendering and frontend polling/reconnect stability improved.
- Widget embed security model replaced Turnstile dependency with per-agent origin whitelist enforcement.

### Documentation

- Updated README.md / README.zh-CN.md with current commands, env vars, architecture, and security model.
- Rewrote tests/README.md around actual test execution entry points, correcting stale directory claims.
- Patched openspec/project.md with missing services and security requirements.
- Added one-command production install documentation to README.md, README.zh-CN.md, and CLAUDE.md.
- Clarified README.md / README.zh-CN.md deployment onboarding by separating automatic deployment from manual deployment.
