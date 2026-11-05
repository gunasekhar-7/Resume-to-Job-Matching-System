# API

Base URL: `http://localhost:8000` (local). Interactive OpenAPI docs: `/docs`.

The API is session-scoped, not multi-user authenticated. The browser receives an opaque,
HttpOnly `talentlens_session` cookie from the upload endpoint; every resume operation is
restricted to that session. Raw upload bytes are never persisted.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness and component status. |
| GET | `/ready` | Readiness; 503 if DB or matching pipeline is unavailable. |
| GET | `/metrics` | Prometheus text exposition. |
| GET | `/api/v1/meta` | Version, non-secret config and in-process metrics. |
| POST | `/api/v1/resumes` | Upload and parse a PDF/DOCX/TXT resume. |
| GET | `/api/v1/resumes` | List resumes owned by the session. |
| GET | `/api/v1/resumes/{id}` | Parsed sections, skills, metadata and retention deadline. |
| DELETE | `/api/v1/resumes/{id}` | Delete parsed text and cascaded match runs. |
| POST | `/api/v1/resumes/{id}/matches` | Rank jobs for the resume. |
| GET | `/api/v1/resumes/{id}/matches` | Latest stored match response. |
| GET | `/api/v1/resumes/{id}/skill-gaps` | Required/preferred gaps; optional `job_ids=a,b`. |
| GET | `/api/v1/jobs` | Job summaries. |
| GET | `/api/v1/jobs/{id}` | Full synthetic job posting. |

## Upload

```bash
curl -i -c cookies.txt \
  -F "file=@data/sample/resumes/r01_priya_single.pdf" \
  http://localhost:8000/api/v1/resumes
```

The response includes `resume_id`, parsed sections and skills, metadata and
`retention_expires_at`. Only the parser's normalised skills are returned; raw file bytes
are not. The `Set-Cookie` token must be reused for later calls.

## Match

```bash
curl -b cookies.txt -X POST \
  -H "Content-Type: application/json" \
  -d '{"top_k": 5, "strategy": "hybrid", "rerank": false,
       "filters": {"work_arrangement": ["remote"]}}' \
  http://localhost:8000/api/v1/resumes/RESUME_ID/matches
```

Response fields include ranked `results`, `score_breakdown` with weights/contributions,
`explanation.section_evidence`, matched/missing skills, experience alignment, model and
index versions, config version and timings. The score is a relevance estimate, not a
hiring probability. `rerank` is accepted but disabled by default because it reduced
held-out NDCG.

Filters are user constraints (`seniority`, `location`, `work_arrangement`,
`employment_type`); they are not scored.

## Errors

```json
{
  "error": {
    "code": "session_required",
    "message": "A valid session cookie is required.",
    "details": {},
    "request_id": "..."
  }
}
```

| Status | Codes / meaning |
| --- | --- |
| 400 | `unsupported_file_type`, `empty_upload`, `unsafe_upload` |
| 401 | `session_required` |
| 403 | `foreign_origin` |
| 404 | `not_found` |
| 413 | `file_too_large` |
| 422 | `validation_error`, `empty_document`, `corrupt_document`, `invalid_request` |
| 429 | `rate_limit_exceeded` |
| 503 | `index_not_built`, `index_load_error`, `model_unavailable` |
| 500 | `internal_error` (no traceback or document content exposed) |

Every response carries `X-Request-ID`; API responses are `Cache-Control: no-store`.

## Limits

- Upload: 10 MB, 20 PDF pages, 120,000 processed characters.
- Supported: PDF (text-based), DOCX, TXT; English only.
- Rate limit: 60 requests/minute per client process by default.
- Login/accounts: not implemented in v1. Do not deploy this as a multi-tenant service
  without adding authentication and per-user authorization.
