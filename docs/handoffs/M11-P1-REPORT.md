# M11+ P1 REPORT — M10+ chain 本机尾巴

> **Scope**: P1-1 only (P1-2/P1-3 DEFER per user-selected option A — local-only follow-up).
> **Branch**: `feat/m9-stream-think-stripper`
> **Baseline**: `3db9039` (post-P0). No backend/frontend/business-doc code change in this PR.
> **Conclusion**: **CONDITIONAL PASS** — P1-1 ✅ 4/4 gates; P1-2/P1-3 DEFER to M11+ P2 (本机).

---

## 1. Background

M10+4 §8 marked sandbox-test Dify apps as `DEFER` (cleanup left because the sandbox session ended). Kickoff (`docs/handoffs/M11-P1-KICKOFF.md`) split the tail into three sub-tasks:

| Sub | Action | Where it can run |
|-----|--------|------------------|
| P1-1 | Delete sandbox test apps on 124.243.178.156:8501 | Sandbox HTTP works ✅ |
| P1-2 | `docker compose --profile dify up -d` (3 GB image) | 本机 only (sandbox can’t pull) |
| P1-3 | Playwright `chat_stream` real spec | 本机 only (cmd.exe spawn blocked in sandbox) |

User selected **option A**: finish P1-1 in this session, leave P1-2/P1-3 for 本机.

---

## 2. P1-1 execution

### 2.1 Dry-run (list-only)

One-off Python script (`urllib + http.cookiejar`, env-fed credentials, never committed to the repo):

1. `POST /console/api/login` with `password` base64-encoded (D9b shape).
2. Echo `csrf_token` cookie back as `X-CSRF-Token` header (Dify 1.14.2 double-submit pattern; missing it returns `401 CSRF token is missing or invalid`).
3. Paginated `GET /console/api/apps?page=N&limit=50`.

Result: **6 apps total**, of which **3** matched the M10+/test pattern — not 6 as M10+4 §8 suggested. Likely cause: the M10+4 7-step E2E retried publish/sync several times against the same app shells, so several attempts shared the same logical app instead of creating fresh ones. The on-server reality is the authority — 3 it is.

### 2.2 Candidates and keepers

| Class | ID | Name | Mode | Created (epoch) |
|-------|------|------|------|------------------|
| DELETE | `3d0f30ed-2fe0-474d-8b29-a441b42e3ec8` | M10plus4 | workflow | 1781578361 |
| DELETE | `e97d2891-cfbe-4647-8db3-85ac83435266` | M10plus4 | workflow | 1781578268 |
| DELETE | `b72dddc1-f2eb-45b9-88c2-4fdb3b8cd30a` | M10plus4-probe | workflow | 1781578194 |
| KEEP | `f1843b90-9847-43cd-b752-8cfe6f28d7a7` | AI_health_consultant | workflow | 1781316906 |
| KEEP | `8222073d-c49e-4998-9240-74d96514bacd` | china_charge_seriver_v2 | workflow | 1781277072 |
| KEEP | `303cf710-4684-4462-9010-945a8fc3a1f3` | China_charge_seriver | workflow | 1781167712 |

Three DELETE timestamps cluster within ~3 minutes during the M10+4 E2E window — unambiguously sandbox artefacts. User confirmed deletion of all three.

### 2.3 Delete

`DELETE /console/api/apps/{id}` returned `HTTP 204` for all 3 targets. Re-list immediately afterwards showed **3 apps** remaining, all three KEEP business apps untouched.

---

## 3. Hard gates

| Gate | Definition | Result |
|------|------------|--------|
| G1.1 | Dry-run list contained target IDs | **PASS** (3/3 present in `before`) |
| G1.2 | All target IDs absent after DELETE | **PASS** (survivors=[]) |
| G1.3 | Business app IDs still present after DELETE | **PASS** (casualties=[]) |
| G1.4 | `len(before) - len(after) == ok_deletes` | **PASS** (6 − 3 == 3) |

Audit JSON: `%TEMP%/p1-1-audit.json` (machine-readable record of before/after/results/gates).

---

## 4. What did NOT run

| Sub | Reason | Where it goes |
|-----|--------|---------------|
| P1-2 docker compose dify | 3 GB image, environment-dependent; needs 本机 disk + clean state | M11+ P2 (本机) |
| P1-3 Playwright `chat_stream` E2E | Sandbox blocks `cmd.exe` spawn (Playwright 1.60); requires 本机 Git Bash or CI | M11+ P2 (本机) |

These are not technical blockers in the code; they are environment-class tasks that the kickoff already pre-classified as 本机-only.

---

## 5. Sandbox vs 本机 breakdown

| Capability | Sandbox observed | 本机 expected |
|------------|------------------|----------------|
| Dify HTTP to 124.243.178.156:8501 | ✅ login/list/delete all clean | ✅ |
| Pull `langgenius/dify-api:1.14.2` (~3 GB) | ❌ DEFER | ✅ |
| Start `basjoo-dify` container | ❌ DEFER (depends on pull) | ✅ |
| Playwright real spec (cmd.exe spawn) | ❌ Windows 1.60 spawn block | ✅ Git Bash |
| Widget E2E (`test:e2e:widget`) | ❌ same root cause | ✅ |

---

## 6. Side effects / blast radius

- 3 Dify apps deleted on the shared host. Irreversible at the API level; rebuilding from Dify Console would lose workflow draft state — none of the 3 had business workflow content (sandbox shells), so blast radius is zero.
- No basjoo backend/frontend/db touched. No DB row touched. No business app touched.
- Repo working tree unchanged except for this REPORT + the prior KICKOFF doc (force-added because `/docs/*` is gitignored by default).
- Dify admin credentials were passed inline via env vars to a one-shot script under `%TEMP%`; the scripts are not in the repo and credentials are not in any commit / report / log file written to git history.

---

## 7. Risks & follow-ups for M11+ P2

1. **Stale "6 apps" expectation in M10+4 §8** — recommend updating the M10+4 doc with a footnote pointing here so future readers don’t hunt for 3 missing apps.
2. **P1-2 docker compose dify on 本机** — run the kickoff §P1-2 6-step procedure; needs 4–6 GB free.
3. **P1-3 Playwright** — `npm run test:e2e -- specs/07-think-streaming.spec.ts` + `npm run test:e2e:widget`; depends on P1-2 if the spec hits the local Dify, otherwise can use 124.243.178.156:8501.
4. **CSRF header note** — the kickoff §P1-1 cURL template doesn’t mention `X-CSRF-Token`. Dify 1.14.2 requires it for non-login console endpoints; update the template if anyone reruns the procedure with raw cURL.

---

## 8. Files touched in this PR

| File | Reason |
|------|--------|
| `docs/handoffs/M11-P1-REPORT.md` | this file (force-added; `/docs/*` is gitignored) |
| `docs/handoffs/M11-P1-KICKOFF.md` | pre-written in the prior session, force-added together |

Zero source code touched. Zero schema migration. Zero dependency changed.

---

## 9. Definition of done

- [x] P1-1 hard gates G1.1–G1.4 all PASS
- [x] Audit JSON written
- [x] No business app harmed
- [x] No credentials in git history / report / logs
- [ ] P1-2 docker compose dify (DEFER to M11+ P2)
- [ ] P1-3 Playwright real spec (DEFER to M11+ P2)
- [x] REPORT committed and pushed

---

## 10. Verdict

**CONDITIONAL PASS** — P1-1 complete and clean (4/4 gates). P1-2 and P1-3 explicitly DEFER to M11+ P2 per user-selected option A; this is a scope decision, not a quality regression. The M10+4 §8 cleanup debt is closed.
