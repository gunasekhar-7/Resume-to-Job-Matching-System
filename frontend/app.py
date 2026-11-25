"""TalentLens Candidate Mode.

Run with:
    streamlit run frontend/app.py

The Streamlit server talks to the FastAPI service over HTTP. The API session cookie is
stored in Streamlit's server-side session state; it is never exposed to the browser as
application data.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

API_URL = (
    os.environ.get("TALENTLENS_API_URL")
    or os.environ.get("TALENTLENS_FRONTEND_API_URL")
    or "http://localhost:8000"
).rstrip("/")
API_TOKEN = os.environ.get("TALENTLENS_API_TOKEN", "").strip()
UI_AUTH_REQUIRED = os.environ.get("TALENTLENS_UI_AUTH", "false").lower() == "true"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def identity_token() -> str:
    """Return the OIDC ID token only inside the server-side Streamlit process."""
    if not UI_AUTH_REQUIRED:
        return ""
    try:
        return str(st.user.tokens.get("id", "") or "")
    except Exception:  # noqa: BLE001 - missing expose_tokens is an auth configuration error
        return ""


def api_client() -> httpx.Client:
    token = st.session_state.get("session_token")
    cookies = {"talentlens_session": token} if token else {}
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    identity = identity_token()
    if identity:
        headers["X-TalentLens-Id-Token"] = identity
    return httpx.Client(base_url=API_URL, cookies=cookies, headers=headers, timeout=TIMEOUT)


def remember_cookie(response: httpx.Response) -> None:
    token = response.cookies.get("talentlens_session")
    if token:
        st.session_state["session_token"] = token


def error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error", {})
        return f"{error.get('code', 'error')}: {error.get('message', response.text[:300])}"
    except Exception:
        return f"HTTP {response.status_code}: {response.text[:300]}"


def call(method: str, path: str, **kwargs) -> tuple[bool, Any]:
    try:
        with api_client() as client:
            response = client.request(method, path, **kwargs)
        remember_cookie(response)
    except httpx.HTTPError as exc:
        st.error(f"The TalentLens API could not be reached at {API_URL}. ({type(exc).__name__})")
        return False, None
    if response.status_code >= 400:
        st.error(error_message(response))
        return False, None
    if response.status_code == 204:
        return True, None
    return True, response.json()


def score_label(value: float) -> str:
    return f"{value:.3f}"


def render_score_breakdown(match: dict[str, Any]) -> None:
    breakdown = match["score_breakdown"]
    st.markdown("**Score components**")
    rows = {
        "Semantic similarity": breakdown["semantic"],
        "Section relevance": breakdown["section_relevance"],
        "Required skills": breakdown["required_coverage"],
        "Preferred skills": breakdown["preferred_coverage"],
        "Experience alignment": breakdown["experience_alignment"],
    }
    st.bar_chart(rows, horizontal=True)
    st.caption(
        f"Final matching score: {score_label(match['score'])}. "
        "This is a relevance estimate, not a probability of being hired."
    )


def render_match(match: dict[str, Any]) -> None:
    title = f"{match['rank']}. {match['title']} — {match['company']}"
    with st.expander(f"{title}  ·  score {score_label(match['score'])}"):
        cols = st.columns(3)
        cols[0].metric("Matching score", score_label(match["score"]))
        cols[1].metric("Retrieval", match["retrieval_source"])
        experience = match["explanation"]["experience"]
        cols[2].metric("Experience", experience["status"].replace("_", " ").title())

        explanation = match["explanation"]
        st.markdown(f"**Why it matched:** {explanation['summary']}")
        render_score_breakdown(match)

        st.markdown("**Resume evidence**")
        if explanation["section_evidence"]:
            for evidence in explanation["section_evidence"]:
                st.markdown(
                    f"`{evidence['section']}` · similarity {evidence['similarity']:.3f}"
                    + (
                        f" · characters {evidence['start_char']}–{evidence['start_char'] + len(evidence['sentence'])}"
                        if evidence.get("start_char") is not None
                        else ""
                    )
                )
                # st.text avoids rendering document text as Markdown or HTML.
                st.text(evidence["sentence"])
        else:
            st.info("No resume sentence crossed the evidence similarity threshold for this job.")

        st.markdown("**Matched skills**")
        if explanation["matched_skills"]:
            st.write(
                ", ".join(
                    f"{item['canonical']} ({item['match_type']}, {item['resume_section']})"
                    for item in explanation["matched_skills"]
                )
            )
        else:
            st.caption("No required or preferred skills were evidenced in the document.")

        left, right = st.columns(2)
        with left:
            st.markdown("**Required skills not evidenced**")
            for item in explanation["missing_required"]:
                st.write(f"- {item['canonical']}")
            if not explanation["missing_required"]:
                st.caption("None.")
        with right:
            st.markdown("**Preferred skills not evidenced**")
            for item in explanation["missing_preferred"]:
                st.write(f"- {item['canonical']}")
            if not explanation["missing_preferred"]:
                st.caption("None.")

        st.caption(
            "Missing means not evidenced in the uploaded document; it does not prove the "
            "candidate lacks the skill. Location and work arrangement are user filters, not "
            "competency signals."
        )
        if explanation["experience"].get("notes"):
            st.markdown(f"**Experience note:** {explanation['experience']['notes']}")
        if match.get("rerank_score") is not None:
            st.caption(
                "Final order uses a cross-encoder; the displayed matching score remains the "
                f"hybrid score. Rerank relevance: {match['rerank_score']:.3f}."
            )


def render_gaps(resume_id: str, match_ids: list[str]) -> None:
    params = {"job_ids": ",".join(match_ids)} if match_ids else None
    ok, payload = call("GET", f"/api/v1/resumes/{resume_id}/skill-gaps", params=params)
    if not ok:
        return
    report = payload["report"]
    st.subheader("Skill gaps")
    cols = st.columns(3)
    cols[0].metric("Jobs analysed", report["jobs_analyzed"])
    cols[1].metric("Average required coverage", f"{report['required_coverage_avg']:.1%}")
    cols[2].metric("Average preferred coverage", f"{report['preferred_coverage_avg']:.1%}")
    st.caption(
        "Coverage is based only on evidence in the uploaded document. Required and preferred "
        "skills are reported separately; a missing skill is not a claim that the candidate "
        "lacks it."
    )
    left, right = st.columns(2)
    with left:
        st.markdown("**Most frequent required gaps**")
        for item in report["frequently_missing_required"]:
            st.write(f"- {item['canonical']} — in {item['job_count']} job(s)")
        if not report["frequently_missing_required"]:
            st.caption("No required gaps in the selected jobs.")
    with right:
        st.markdown("**Most frequent preferred gaps**")
        for item in report["frequently_missing_preferred"]:
            st.write(f"- {item['canonical']} — in {item['job_count']} job(s)")
        if not report["frequently_missing_preferred"]:
            st.caption("No preferred gaps in the selected jobs.")

    st.markdown("**Per-job detail**")
    for item in report["per_job"]:
        with st.expander(f"{item['job_id']} · {item['title']}"):
            st.write(
                f"Required coverage {item['required_coverage']:.1%}; preferred coverage "
                f"{item['preferred_coverage']:.1%}."
            )
            st.write(
                "Not evidenced (required): "
                + (", ".join(skill["canonical"] for skill in item["required_missing"]) or "none")
            )
            st.write(
                "Not evidenced (preferred): "
                + (", ".join(skill["canonical"] for skill in item["preferred_missing"]) or "none")
            )
    if report["ambiguous_skills"]:
        st.warning(
            "Some extracted skills were ambiguous: "
            + ", ".join(item["canonical"] for item in report["ambiguous_skills"])
        )


def main() -> None:
    st.set_page_config(page_title="TalentLens Candidate Mode", page_icon="🔎", layout="wide")
    if UI_AUTH_REQUIRED and not st.user.is_logged_in:
        st.login()
        st.stop()
    if UI_AUTH_REQUIRED:
        identity_key = str(getattr(st.user, "sub", "") or getattr(st.user, "email", "") or "")
        if st.session_state.get("identity_key") != identity_key:
            for key in ("resume", "match", "session_token", "jobs", "delete_notice"):
                st.session_state.pop(key, None)
            st.session_state["identity_key"] = identity_key
        if not identity_token():
            st.error(
                "OIDC is enabled but no ID token is exposed. Add `expose_tokens = \"id\"` "
                "to the [auth] section of .streamlit/secrets.toml."
            )
            st.stop()
    st.title("TalentLens")
    delete_notice = st.session_state.pop("delete_notice", None)
    if delete_notice:
        st.success(delete_notice)
    st.caption(
        "Explainable resume-to-job matching. Every recommendation cites evidence from your "
        "resume. Scores are relevance estimates, never probabilities of being hired, and no "
        "automated hiring decision is made."
    )

    with st.sidebar:
        st.header("Session")
        st.caption(f"API: {API_URL}")
        if UI_AUTH_REQUIRED:
            st.caption(f"Signed in as {getattr(st.user, 'email', 'SSO user')}")
            if st.button("Sign out"):
                st.logout()
                st.stop()
        if st.button("Clear this UI session"):
            for key in ("resume", "match", "session_token", "jobs"):
                st.session_state.pop(key, None)
            st.rerun()
        st.divider()
        st.markdown(
            "**Privacy**\n\n"
            "- Raw uploaded bytes are never stored.\n"
            "- Parsed text is retained for 24 hours by default and is deletable.\n"
            "- Resume content is processed locally by the configured API, not sent to an "
            "external AI service."
        )

    uploaded = st.file_uploader("Upload a resume (PDF, DOCX or TXT)", type=["pdf", "docx", "txt"])
    if uploaded is not None and st.button("Analyse resume", type="primary"):
        files = {"file": (uploaded.name, uploaded.getvalue(), uploaded.type or "application/octet-stream")}
        ok, payload = call("POST", "/api/v1/resumes", files=files)
        if ok:
            st.session_state["resume"] = payload
            st.session_state.pop("match", None)
            st.success("Resume parsed. Review the extracted information, then rank jobs.")

    resume = st.session_state.get("resume")
    if not resume:
        st.info("Upload a resume to see ranked jobs, evidence and skill gaps.")
        return

    resume_id = resume["resume_id"]
    metadata = resume["metadata"]
    st.subheader("Parsed resume")
    cols = st.columns(3)
    cols[0].metric("Status", metadata["parsing_status"])
    cols[1].metric("Extraction quality", f"{metadata['extraction_quality']:.2f}")
    cols[2].metric("Skills found", len(resume["skills"]))
    if metadata.get("warnings"):
        with st.expander(f"Parsing warnings ({len(metadata['warnings'])})"):
            for warning in metadata["warnings"]:
                st.warning(warning)

    with st.expander("Extracted sections and skills", expanded=False):
        for section, lines in resume["sections"].items():
            if lines:
                st.markdown(f"**{section.title()}**")
                for line in lines:
                    st.text(line)
        st.markdown("**Normalised skills**")
        st.write(", ".join(sorted({skill["canonical"] for skill in resume["skills"]})) or "None found.")
        st.caption("Resume text is shown for review; it is never interpreted as instructions.")

    st.subheader("Rank jobs")
    with st.form("matching-form"):
        left, mid, right = st.columns(3)
        with left:
            strategy = st.selectbox("Retrieval strategy", ["hybrid", "semantic", "tfidf"])
            top_k = st.slider("Number of recommendations", min_value=1, max_value=23, value=10)
        with mid:
            location = st.text_input("Location contains (optional)", "")
            arrangement = st.multiselect(
                "Work arrangement (optional)", ["remote", "hybrid", "onsite"]
            )
        with right:
            seniority = st.multiselect(
                "Seniority (optional)", ["junior", "junior-mid", "mid", "mid-senior", "senior", "manager"]
            )
            rerank = st.checkbox(
                "Cross-encoder reranking (experimental)",
                help="Disabled by default: it reduced held-out NDCG@10 in this project.",
            )
        submitted = st.form_submit_button("Rank jobs", type="primary")

    if submitted:
        filters: dict[str, Any] = {}
        if location:
            filters["location"] = location
        if arrangement:
            filters["work_arrangement"] = arrangement
        if seniority:
            filters["seniority"] = seniority
        ok, payload = call(
            "POST",
            f"/api/v1/resumes/{resume_id}/matches",
            json={
                "top_k": top_k,
                "strategy": strategy,
                "filters": filters or None,
                "rerank": rerank,
            },
        )
        if ok:
            st.session_state["match"] = payload

    match = st.session_state.get("match")
    tabs = st.tabs(["Recommendations", "Skill gaps", "All jobs"])
    with tabs[0]:
        if not match:
            st.info("Choose filters and select Rank jobs.")
        else:
            st.caption(
                f"{len(match['results'])} results · {match['retrieval']} · model "
                f"{match['model_id']} · index {match['index_version']} · config "
                f"{match['config_version']}"
            )
            if match.get("warnings"):
                for warning in match["warnings"]:
                    st.warning(warning)
            for result in match["results"]:
                render_match(result)
                st.divider()
            st.caption(
                "Location, work arrangement and seniority are filters. Name, contact details, "
                "age and education prestige are excluded from scoring."
            )
    with tabs[1]:
        if not match:
            st.info("Rank jobs first to focus the gap report on recommendations.")
        else:
            render_gaps(resume_id, [item["job_id"] for item in match["results"]])
    with tabs[2]:
        if "jobs" not in st.session_state:
            ok, jobs = call("GET", "/api/v1/jobs")
            if ok:
                st.session_state["jobs"] = jobs
        jobs = st.session_state.get("jobs")
        ok = jobs is not None
        if ok:
            for job in jobs:
                with st.expander(f"{job['job_id']} · {job['title']} · {job['company']}"):
                    st.write(
                        f"{job.get('location') or 'Location not stated'} · "
                        f"{job.get('work_arrangement', 'unknown')} · "
                        f"{job.get('seniority') or 'seniority not stated'}"
                    )
                    st.write("Required: " + ", ".join(job["required_skills"]))

    st.divider()
    if st.button("Delete my resume and retained matching data", type="secondary"):
        ok, _ = call("DELETE", f"/api/v1/resumes/{resume_id}")
        if ok:
            for key in ("resume", "match"):
                st.session_state.pop(key, None)
            st.session_state["delete_notice"] = (
                "Resume and matching data deleted from the API database."
            )
            st.rerun()


if __name__ == "__main__":
    main()
