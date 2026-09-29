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
def build_service() -> tuple[dict, KnowledgeService]:
    users = load_users()
    service = KnowledgeService(
        load_documents(),
        audit_path=PROJECT_ROOT / "runtime" / "audit.jsonl",
    )
    return users, service


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

users, service = build_service()

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
    user = users[selected_user_id]
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
                st.session_state["result"] = service.ask(user, question.strip())

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
        st.caption("Excluded document titles are intentionally hidden.")

        for index, item in enumerate(result.evidence, start=1):
            document = item.document
            with st.expander(f"[{index}] {document.source} · {document.title}"):
                st.write(document.content)
                st.caption(
                    f"classification={document.classification} · status={document.status} · "
                    f"updated={document.updated_at} · retrieval_score={item.score}"
                )
                st.success(item.access_reason)

        with st.expander("Current request audit record"):
            st.json(result.audit_record)

st.divider()
st.caption(
    "MVP v0 · Synthetic data only · Real authentication, connectors, embeddings, "
    "temporal conflict reasoning, and cloud deployment are planned iterations."
)

