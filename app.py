from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.data import load_documents, load_users
from src.service import KnowledgeService


PROJECT_ROOT = Path(__file__).resolve().parent
PRESET_QUESTIONS = [
    "SG Batch Payments v2.3 是否已经正式上线？最近失败事故的原因是什么？我们现在能否向客户确认服务已经恢复？",
    "What was the technical root cause of the SG Batch Payments incident?",
    "Can Operations tell affected customers that service has recovered?",
]


@st.cache_resource
def build_service() -> KnowledgeService:
    users = load_users()
    return KnowledgeService(
        load_documents(),
        audit_path=PROJECT_ROOT / "runtime" / "audit-v2.jsonl",
        users=users,
    )


st.set_page_config(page_title="ContextLedger", page_icon="🧭", layout="wide")
st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; max-width: 1500px;}
      .identity-card {padding: 1rem; border: 1px solid #d7dde8; border-radius: 12px; background: #f7f9fc;}
      .small-muted {color: #64748b; font-size: 0.9rem;}
      .stAlert {border-radius: 10px;}
    </style>
    """,
    unsafe_allow_html=True,
)

service = build_service()
users = service.list_users()

st.title("ContextLedger")
st.caption("Permission-aware enterprise knowledge assistant · synthetic FinTech MVP")

identity_col, query_col, evidence_col = st.columns([1.0, 2.0, 1.35], gap="large")

with identity_col:
    st.subheader("1 · Identity")
    selected_user_id = st.selectbox(
        "Act as",
        options=list(users),
        format_func=lambda user_id: f"{users[user_id].name} · {users[user_id].role}",
    )
    user = service.get_user(selected_user_id)
    projects = ", ".join(user.projects) if user.projects else "none"
    st.markdown(
        f"""
        <div class="identity-card">
          <strong>{user.name}</strong><br/>
          <span class="small-muted">
          Department: {user.department}<br/>
          Role: {user.role}<br/>
          Clearance: {user.clearance}<br/>
          Projects: {projects}<br/>
          Employment: {user.employment_type}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info("Demo identities are synthetic. Access is checked before retrieval.")

    if user.role == "compliance_officer":
        st.markdown("#### Live permission change")
        target_user_id = st.selectbox(
            "Target identity",
            options=[user_id for user_id in users if user_id != user.id],
            format_func=lambda user_id: users[user_id].name,
        )
        target = service.get_user(target_user_id)
        st.caption(f"Current projects: {', '.join(target.projects) or 'none'}")
        revoke_col, restore_col = st.columns(2)
        if revoke_col.button("Revoke payments-sg", use_container_width=True):
            service.revoke_project_access(user.id, target_user_id, "payments-sg")
            st.success(f"Revoked payments-sg from {target.name}. Subsequent queries use the new permission.")
        if restore_col.button("Reset identity", use_container_width=True):
            service.reset_identity(user.id, target_user_id)
            st.success(f"Restored {target.name} to the baseline demo permissions.")

        st.markdown("#### Freshness demo")
        document_options = {document.id: document for document in service.list_documents()}
        freshness_document_id = st.selectbox(
            "Source document",
            options=list(document_options),
            format_func=lambda document_id: f"{document_options[document_id].source} · {document_id}",
        )
        freshness_document = document_options[freshness_document_id]
        freshness_state = service.freshness.evaluate(freshness_document)
        st.caption(
            f"{freshness_state.status}: indexed={freshness_document.updated_at}, "
            f"source={freshness_document.source_updated_at}, synced={freshness_document.synced_at}"
        )
        stale_col, sync_col = st.columns(2)
        if stale_col.button("Simulate source update", use_container_width=True):
            service.mark_source_updated(user.id, freshness_document_id)
            st.warning("The indexed copy is now stale and will be excluded from retrieval.")
        if sync_col.button("Sync latest version", use_container_width=True):
            service.sync_document(user.id, freshness_document_id)
            st.success("The indexed version now matches the latest known source version.")

with query_col:
    st.subheader("2 · Ask")
    preset = st.selectbox("Preset question", PRESET_QUESTIONS)
    question = st.text_area("Question", value=preset, height=130)
    submitted = st.button("Investigate with authorised evidence", type="primary", use_container_width=True)

    if submitted:
        if not question.strip():
            st.warning("Enter a question first.")
        else:
            with st.spinner("Checking policy, retrieving evidence, and writing audit record..."):
                st.session_state["result"] = service.ask(user.id, question.strip())

    result = st.session_state.get("result")
    if result:
        if result.user.id != user.id:
            st.warning("The answer below belongs to the previously selected identity. Submit again to re-run with the current identity.")
        st.markdown("#### Answer")
        if result.decision == "insufficient":
            st.warning(result.answer)
        else:
            st.markdown(result.answer)
        st.caption(f"Provider: {result.provider} · Request: {result.request_id}")
    else:
        st.markdown("#### Answer")
        st.write("Submit a question to create the first audited answer.")

with evidence_col:
    st.subheader("3 · Evidence & Audit")
    result = st.session_state.get("result")
    if not result:
        st.write("Authorised evidence and the audit summary will appear here.")
    else:
        st.metric("Authorised evidence used", len(result.evidence))
        st.metric("Documents excluded by policy", result.denied_document_count)
        st.metric("Documents excluded as stale", result.stale_document_count)
        st.caption("Excluded document titles are intentionally hidden from the requester.")

        for index, item in enumerate(result.evidence, start=1):
            document = item.document
            with st.expander(f"[{index}] {document.source} · {document.title}"):
                st.write(document.content)
                st.caption(
                    f"classification={document.classification} · status={document.status} · "
                    f"indexed_updated={document.updated_at} · source_updated={document.source_updated_at} · "
                    f"synced={document.synced_at} · freshness={item.freshness_status} · "
                    f"retrieval_score={item.score}"
                )
                st.success(item.access_reason)
                st.info(item.freshness_reason)

        with st.expander("Current request audit record"):
            st.json(result.audit_record)

    verification = service.audit_integrity()
    with st.expander("Audit chain integrity"):
        if verification.valid:
            st.success(f"Valid chain · events={verification.event_count} · head={verification.head_hash[:16]}…")
        else:
            st.error(f"Audit integrity failure: {verification.error}")

    if user.role == "compliance_officer":
        with st.expander("Compliance audit inquiry"):
            audit_question = st.text_input(
                "Natural-language audit question",
                value="Show me what alice accessed related to jira-002 in the last 30 days",
            )
            if st.button("Run natural-language audit query", use_container_width=True):
                st.session_state["audit_results"] = service.query_audit_text(user.id, audit_question)
            st.caption("Advanced deterministic filters")
            audit_user = st.selectbox("Filter by user", ["all", *users.keys()])
            audit_document = st.text_input("Document ID (optional)")
            if st.button("Query audit trail", use_container_width=True):
                st.session_state["audit_results"] = service.query_audit(
                    user.id,
                    user_id=None if audit_user == "all" else audit_user,
                    document_id=audit_document.strip() or None,
                )
            audit_results = st.session_state.get("audit_results")
            if audit_results is not None:
                st.caption(f"{len(audit_results)} matching events; this audit inquiry was also logged.")
                st.json(audit_results)

st.divider()
st.caption(
    "MVP v0 · Synthetic data only · Real authentication, connectors, embeddings, "
    "temporal conflict reasoning, and cloud deployment are planned iterations."
)
