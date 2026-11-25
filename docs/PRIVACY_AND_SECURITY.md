# Privacy and Security Review

## Data flow

```text
browser upload
  -> FastAPI validates extension, size, magic bytes, DOCX ZIP limits
  -> bytes parsed in memory (PDF/DOCX/TXT)
  -> parsed ResumeDocument
  -> PostgreSQL/SQLite stores parsed JSON with retention deadline
  -> matching uses the stored parsed document
  -> raw uploaded bytes are discarded
```

No external AI service receives resume text. The embedding model runs locally on CPU.
Job postings are synthetic and contain no candidate data.

## What is stored

| Data | Stored? | Notes |
| --- | --- | --- |
| Raw PDF/DOCX/TXT bytes | No | In memory only; no temp path. |
| Parsed text, sections, skills, metadata | Yes, default 24 h | Structured PII is replaced with `privacy.redaction_placeholder` before storage; deleted on expiry or user request. |
| Match results | Yes, with the resume | Cascades on resume deletion; replaced on each new run. |
| Upload filename | Yes | Display/audit only; basename sanitised. |
| Structured PII values | No | Email, phone and profile/URL values are redacted in stored text; only types are recorded. Names are not detected by the default regex scanner. |
| Session cookie | Browser only | Opaque random token; only a SHA-256 hash is stored server-side. |

## Access control

The API requires a service bearer token (`TALENTLENS_API_TOKEN`) in production and in the
Docker profile; missing tokens fail closed at startup. A random HttpOnly, SameSite=Lax
cookie identifies one browser session. Every resume lookup is filtered by that session's
ID. A second session cannot read, match or delete the first session's resume.

When OIDC is configured, the trusted Streamlit server forwards the signed ID token and the
API verifies issuer, audience, signature and expiry before storing `issuer#subject` in
`session_identities`. Anonymous access never inherits an identity-bound session, and a
different subject cannot reuse the cookie. The raw ID token is not stored. Without OIDC the
deployment remains a single-tenant service boundary.

State-changing requests with a foreign `Origin` header are rejected. The API is
same-origin or explicit CORS allow-list by default, uses `no-store` on API responses, and
sets `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and
`Permissions-Policy`.

## Retention and deletion

- Default retention: 24 hours (`TALENTLENS_RESUME_RETENTION_HOURS`).
- Expired sessions and resumes are purged at API startup and by a background sweep (default
  hourly; `TALENTLENS_RETENTION_PURGE_INTERVAL_SECONDS=0` disables the sweep).
- `DELETE /api/v1/resumes/{id}` deletes the resume and cascades its match runs. The raw
  upload was never stored.
- The Streamlit UI exposes the delete action.
- A production deployment should add an external scheduler for periods when the API process
  is stopped and take database backups according to its own policy.

## Upload and parsing hardening

- Extension allow-list (`.pdf`, `.docx`, `.txt`), 10 MB cap, magic-byte checks.
- DOCX ZIP member count and uncompressed-size limits.
- No temp files and no path-based access from user input.
- Text capped at 120,000 characters for processing.
- Structured PII is redacted before section detection, skill extraction, embeddings and
  persistence, so offsets and evidence refer to the redacted representation.
- Heading-less documents never use raw full text as a scoring fallback. Only extracted
  skill names are used; if none exist, semantic and TF-IDF signals are neutral and the
  response carries a warning. Names, contact details and education therefore cannot
  change a heading-less ranking.
- Parsed content is never logged; logs include IDs, counts and timings only.
- Low-text or corrupt documents fail visibly rather than producing a silent empty ranking.

## API controls

- Per-process rate limit (60 requests/minute by default).
- Declared request bodies over 11 MB are rejected before multipart/file parsing; chunked
  bodies are counted while streaming and rejected at the same limit.
- At most 20 active resumes per session by default; excess uploads return a typed 429.
- Request IDs accepted only when alphanumeric/hyphen and bounded; otherwise generated.
- Structured errors do not expose tracebacks or document content.
- Responses set CSP, frame denial, nosniff, no-referrer, CORP and cache controls; HSTS is
  emitted only for HTTPS requests.
- OpenAPI docs are enabled; a production deployment should place the service behind TLS
  and may disable docs at the proxy.

## Residual risks

- Session cookies are bearer tokens; anyone who obtains one can access that session. Use
  TLS and short retention in any real deployment.
- The default regex scanner does not detect personal names or arbitrary free-text PII;
  enable a reviewed NER/Presidio policy before accepting real candidate data at scale.
- OIDC wiring is tested with an injected verifier, not a live provider. Exercise discovery,
  logout and key rotation in the target deployment before relying on per-user authorization.
- The service token still authenticates the deployment; OIDC adds user identity but does not
  replace the service token.
- The per-process rate limiter is not distributed.
- SQLite/PostgreSQL and the host filesystem are outside this review's threat model.
- Synthetic data means no real PII processing has been audited; a DPIA is required before
  using real resumes.
- Memory usage during parsing and embedding is bounded only by the documented limits.
