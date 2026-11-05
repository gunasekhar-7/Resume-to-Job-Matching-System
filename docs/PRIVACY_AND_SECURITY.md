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
| Parsed full text, sections, skills, metadata | Yes, default 24 h | `privacy.persist_parsed_text` and `resume_retention_hours`; deleted on expiry or user request. |
| Match results | Yes, with the resume | Cascades on resume deletion; replaced on each new run. |
| Upload filename | Yes | Display/audit only; basename sanitised. |
| PII values | Not in metadata | PII types are recorded; values are not used in scoring or logs. |
| Session cookie | Browser only | Opaque random token; only a SHA-256 hash is stored server-side. |

## Access control

This is a single-user, session-scoped v1. A random HttpOnly, SameSite=Lax cookie identifies
one browser session. Every resume lookup is filtered by that session's ID. A second
session cannot read, match or delete the first session's resume. This is not multi-user
authentication and must not be represented as such.

State-changing requests with a foreign `Origin` header are rejected. The API is
same-origin or explicit CORS allow-list by default, uses `no-store` on API responses, and
sets `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and
`Permissions-Policy`.

## Retention and deletion

- Default retention: 24 hours (`TALENTLENS_RESUME_RETENTION_HOURS`).
- Expired sessions and resumes are purged at API startup and can be purged by calling
  `Storage.purge_expired()`.
- `DELETE /api/v1/resumes/{id}` deletes the resume and cascades its match runs. The raw
  upload was never stored.
- The Streamlit UI exposes the delete action.
- A production deployment should run the purge on a schedule and take database backups
  according to its own policy.

## Upload and parsing hardening

- Extension allow-list (`.pdf`, `.docx`, `.txt`), 10 MB cap, magic-byte checks.
- DOCX ZIP member count and uncompressed-size limits.
- No temp files and no path-based access from user input.
- Text capped at 120,000 characters for processing.
- Parsed content is never logged; logs include IDs, counts and timings only.
- Low-text or corrupt documents fail visibly rather than producing a silent empty ranking.

## API controls

- Per-process rate limit (60 requests/minute by default).
- Request IDs accepted only when alphanumeric/hyphen and bounded; otherwise generated.
- Structured errors do not expose tracebacks or document content.
- OpenAPI docs are enabled; a production deployment should place the service behind TLS
  and may disable docs at the proxy.

## Residual risks

- Session cookies are bearer tokens; anyone who obtains one can access that session. Use
  TLS and short retention in any real deployment.
- The per-process rate limiter is not distributed.
- SQLite/PostgreSQL and the host filesystem are outside this review's threat model.
- Synthetic data means no real PII processing has been audited; a DPIA is required before
  using real resumes.
- Memory usage during parsing and embedding is bounded only by the documented limits.
