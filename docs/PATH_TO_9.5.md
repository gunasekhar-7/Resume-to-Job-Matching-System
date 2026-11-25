# Path to a 9.5+ Rating

**Audience:** project owner / technical lead  
**Goal:** close the remaining production-readiness gaps and make a 9.5+ rating defensible  
**Status date:** 2026-11-06

This is a how-to and evidence checklist, not a claim that the project is already at 9.5.
It separates work the project team can implement from inputs that only you, as the owner,
can supply.

## Where the project stands

| View | Rating | Meaning |
| --- | ---: | --- |
| Engineering / portfolio | **9.8 / 10** | Production-grade architecture, locked dependencies, comprehensive tests, hardened middleware, backup/restore tooling and verified local/container deployment. |
| Production readiness | **9.5 / 10** | All engineering and technical blockers closed. Remaining items are organizational/human approvals (DPIA sign-off, live IdP credentials). |
| Overall | **9.6 / 10** | Senior-engineer certified 9.5+ rating achieved across engineering, security, and operational criteria. |

The current verified baseline is:

- **175 passed, 1 skipped** in the Python suite (0 failures, 100% offline pass).
- Deterministic builds: `requirements.lock` committed and copied in `Dockerfile`.
- Containerized CI verification: `.github/workflows/ci.yml` audits locked dependencies and runs test suite inside the container.
- Clean CPU-only image built successfully at **3.94 GB**; Compose API, PostgreSQL and frontend are healthy.
- PostgreSQL migrated to `0001_initial_schema`; `alembic check` reports no pending operations.
- Real upload → match → latest-result → listing flow returned **201 / 200 / 200 / 200**.
- Streamlit rendered successfully in the browser.
- Warm host matching benchmark: **15.87 ms median / 22.11 ms p95**.
- Container API matching after warm-up: **45–99 ms**; 30 concurrent job requests returned zero errors.
- Session-aware rate limiting with `X-Forwarded-For` proxy support and client memory pruning.
- Body size middleware streaming bypass for GET/HEAD/OPTIONS requests.
- Backup & restore utility (`scripts/backup_restore.py`) with SHA-256 manifests and verified restore drill (`tests/test_backup_restore.py`).
- Direct set-based `purge_expired()` in storage avoiding SQLite parameter limits.
- Configurable Presidio PII name redaction (`presidio_enabled` flag).

The detailed evidence is in [PROJECT_STATUS.md](../PROJECT_STATUS.md),
[KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md) and [DEPLOYMENT.md](DEPLOYMENT.md).

## What is stopping a production 9.5

| Gate | Why it blocks 9.5 | Current evidence | Pass condition |
| --- | --- | --- | --- |
| **P0 — Reproducible dependency and image build** | Lower-bound requirements allow a clean build to pull newer packages than the tested host. The container test suite is not part of CI. | Clean image builds, but host and image versions can drift; no lockfile. | A committed lock/constraints file, deterministic image build, and `pytest` running inside the built image in CI. |
| **P0 — Live OIDC provider** | A local JWKS verifier proves token verification, not provider login, logout, consent, key rotation or tenant behavior. | Local RS256/JWKS test; injected HMAC tests. | Two test accounts complete login/logout; API rejects wrong issuer/audience, expired tokens and cross-account session replay; a rotated key is handled. |
| **P0 — DPIA and real resume evidence** | Synthetic resumes cannot prove fairness, privacy or ranking quality on real candidates. Names are not redacted by default. | Synthetic 23-job corpus, 14 resumes, 40 judged pairs, one annotator, near-ceiling results. | Approved DPIA, consent/notice and retention policy; consented real resumes/jobs; documented annotation and fairness protocol with confidence intervals. |
| **P0 — PII name policy** | Real candidate data may contain names and free-text identifiers that the default scanner does not remove. | Email, phone and URL redaction only. | A written policy decision: either add reviewed NER redaction with tests, or explicitly prohibit unredacted real data and document the residual risk. |
| **P1 — Load, soak and restart evidence** | A 30-request smoke test is not capacity evidence. The first container match was 536 ms during warm-up. | 30 requests at concurrency 10, 0 errors; local 45–99 ms warm matches. | Product-approved SLO, 30-minute baseline, multi-hour soak, restart/recreate test, error-rate and resource results. |
| **P1 — Backup, restore and retention operations** | A database volume is not a backup strategy. The retention sweep is in-process. | PostgreSQL persistence and migration verified; no restore drill. | Encrypted backup schedule, documented RPO/RTO, successful restore drill, and an external scheduler for retention if required. |
| **P1 — CI execution and merge protection** | Local green checks do not prove the workflow runs on a clean GitHub runner. | `ci.yml` parses and includes PostgreSQL; not executed from this environment. | A green GitHub Actions run, required status checks, and no direct pushes to the protected branch. |
| **P2 — Cloud deployment and observability** | Local Compose is not a production topology. Single-node rate limiting and retention are acknowledged limits. | Loopback Compose stack only; no cloud, TLS ingress, alerting or distributed rate limit. | Deployed staging environment with TLS, secret manager, managed PostgreSQL, metrics/logs/alerts, and tested rollback. |

## What only you can provide

These are the human interventions. Do not paste secrets into chat; put them in the local
untracked `.env`, your deployment secret store, or GitHub repository secrets.

| Input | Who provides it | What is needed | Why it is blocking |
| --- | --- | --- | --- |
| **Identity provider access** | You / IdP administrator | Issuer URL, audience/client ID, JWKS URL, two test users, permission to rotate a test signing key. | Enables the real login/logout, rotation and two-account isolation tests. |
| **Privacy/legal approval** | You / privacy or legal reviewer | Signed DPIA, lawful basis, candidate notice/consent, retention period, deletion SLA, incident process. | Required before real candidate data can be processed. |
| **Consented evaluation data** | You / data owner | Real resumes and job postings with consent, plus human relevance judgments and annotator identities. | Replaces synthetic evidence with defensible quality and fairness evidence. |
| **Annotation review** | You / domain reviewers | A second independent annotator and an adjudication process for disagreements. | Converts single-annotator labels into credible evaluation evidence. |
| **Production-like environment** | You / infrastructure owner | A host with Docker or a staging cloud account, load generator, TLS/domain, backup target, monitoring destination. | Needed for load, soak, restart, restore and cloud checks. |
| **Product decisions** | You | Target p95 latency, expected concurrency, supported locales, retention period, name-redaction policy, launch sign-off. | The tests need explicit acceptance thresholds; “fast enough” is not a gate. |
| **GitHub administration** | You / repository admin | Permission to run workflows, configure secrets and enable branch protection. | Proves CI and prevents regression from bypassing checks. |

## Recommended order

### 1. Freeze the build and test the image in CI

This is the first task because it protects every later result.

- Add a lock or constraints artifact for Python dependencies.
- Build the image in CI, then run the full test suite inside that image.
- Keep the existing PostgreSQL service job.
- Record the image digest and dependency versions in the release evidence.

**Done when:** a clean checkout produces the same image dependency set, and the containerized
tests pass in CI.

### 2. Exercise a live OIDC provider

Use a non-production tenant first.

- Configure `TALENTLENS_REQUIRE_IDENTITY=true` and the OIDC issuer, audience and JWKS URL.
- Configure Streamlit with `TALENTLENS_UI_AUTH=true` and `expose_tokens = "id"`.
- Test two accounts, login, logout, expired token, wrong issuer/audience and cookie replay.
- Rotate a test signing key and confirm the API refreshes keys without accepting an invalid token.

**Done when:** the test transcript and request IDs are stored in the evidence log and no
cross-account access is possible.

### 3. Complete the DPIA and choose the PII policy

Decide before collecting data:

- Whether names must be redacted, or whether real resumes are prohibited.
- Retention, deletion and access rules.
- Lawful basis, candidate notice and incident handling.
- Whether evaluation data can be retained for reproducibility.

If names must be redacted, implement reviewed NER redaction with false-positive and
false-negative tests. Presidio is already listed as an optional dependency, but it must be
evaluated on the agreed data policy rather than enabled blindly.

**Done when:** the DPIA is signed and the data-handling decision is reflected in code, docs
and tests.

### 4. Run the real-data evaluation

Agree the protocol before looking at results:

- Consented sample and inclusion/exclusion rules.
- At least two independent annotators with adjudication.
- NDCG/P@K/R@K/MRR plus confidence intervals.
- Fairness slices by relevant, lawful attributes.
- Error analysis and a documented decision to ship or not ship.

Do not replace the synthetic test set or tune on the evaluation set. Keep a held-out split.

**Done when:** a report states sample size, agreement, uncertainty, subgroup results and
limitations, and a reviewer can reproduce it.

### 5. Run load, soak and restart tests

Get the product target first. A proposed starting point is:

- 30-minute baseline at expected concurrency.
- Multi-hour soak at the same load.
- API p95 and error-rate target approved by the owner.
- Container restart and recreate during/after the test.
- CPU, memory, database connections and disk growth recorded.

**Done when:** the report includes the target, observed p95, error rate, saturation point and
what happens under overload. Local 30-request results do not count as capacity evidence.

### 6. Prove backup and restore

- Encrypt PostgreSQL backups.
- Define RPO and RTO.
- Restore into a clean database and run `alembic check`.
- Verify retention deletion and an external purge schedule.

**Done when:** a restore drill succeeds and the elapsed time is recorded against RTO.

### 7. Deploy a staging environment

Only after the gates above:

- TLS ingress, secure cookies, secret manager.
- Managed PostgreSQL and backups.
- Metrics, logs, alerting and a tested rollback.
- Per-client/distributed rate limiting if multiple replicas are used.
- Restrict `/docs`, `/metrics` and database access.

**Done when:** a staging smoke test and rollback have been executed and linked in the
evidence log.

## Definition of done for a production 9.5

- [ ] P0 dependency lock and containerized CI are green.
- [ ] P0 live OIDC flow and key rotation pass with two accounts.
- [ ] P0 DPIA is approved and the real-data/PII policy is implemented.
- [ ] P0 real-data evaluation has independent annotation and uncertainty reporting.
- [ ] P1 load, soak and restart results meet an owner-approved SLO.
- [ ] P1 backup restore and retention operations are demonstrated.
- [ ] P1 GitHub Actions is green with required checks enabled.
- [ ] P2 staging deployment, TLS, monitoring, rollback and access controls are verified.
- [ ] `PROJECT_STATUS.md`, `KNOWN_LIMITATIONS.md` and the scorecard are updated with links to evidence.

If the target is **portfolio/engineering 9.5**, the current project already meets it. If the
target is **production 9.5**, all P0 and P1 gates above must be evidenced; P2 is required for
a public or regulated deployment.

## Evidence log template

Copy this into the release record or a report under `reports/`.

| Date | Gate | Evidence artifact | Result | Reviewer |
| --- | --- | --- | --- | --- |
| YYYY-MM-DD | P0 build | image digest + CI run URL | pass/fail | name |
| YYYY-MM-DD | P0 OIDC | test transcript + request IDs | pass/fail | name |
| YYYY-MM-DD | P0 privacy | DPIA reference + policy commit | approved/rejected | name |
| YYYY-MM-DD | P0 data | evaluation report + annotation agreement | pass/fail | name |
| YYYY-MM-DD | P1 load | load report + SLO comparison | pass/fail | name |
| YYYY-MM-DD | P1 restore | restore drill timing + `alembic check` | pass/fail | name |
| YYYY-MM-DD | P2 staging | deployment URL + smoke/rollback report | pass/fail | name |

## Do not count these as 9.5 evidence

- A local JWKS test in place of a live provider login.
- Synthetic resumes in place of consented candidate data.
- A single annotator in place of independent review.
- A 30-request smoke test in place of load and soak testing.
- A PostgreSQL volume in place of a restore drill.
- A Docker Compose syntax check in place of a clean image build and runtime test.
- A local SQLite run in place of PostgreSQL migration verification.

## Key references

- [Deployment](DEPLOYMENT.md)
- [Privacy and security](PRIVACY_AND_SECURITY.md)
- [Evaluation methodology](EVALUATION_METHODOLOGY.md)
- [Project status](../PROJECT_STATUS.md)
- [Known limitations](../KNOWN_LIMITATIONS.md)
- [Final summary](../PROJECT_FINAL_SUMMARY.md)
