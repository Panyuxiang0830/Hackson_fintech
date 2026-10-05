"use strict";
const el = id => document.getElementById(id);
let me = null, csrf = "", epoch = null, generation = 0, people = [], principals = [], auditData = null;
function clearEvidence() {
  generation++;
  for (const id of ["answer", "reader", "hits"]) { el(id).replaceChildren(); if (id !== "hits") el(id).hidden = true; }
  el("auditresults").textContent = ""; auditData = null; el("auditexport").disabled = true;
}
async function api(path, body) {
  const response = await fetch(path, {cache:"no-store", credentials:"same-origin", headers:body ? {"Content-Type":"application/json", "X-CSRF-Token":csrf} : {}, method:body ? "POST" : "GET", body:body ? JSON.stringify(body) : undefined});
  const payload = await response.json();
  if (!response.ok) { if ([401,403,409].includes(response.status)) clearEvidence(); throw new Error(payload.error || "请求失败"); }
  return payload;
}
function option(select, value, text) { const o = document.createElement("option"); o.value=value; o.textContent=text; select.append(o); }
async function sessionStatus() {
  const status = await api("/api/session");
  const previousId = me && me.id;
  if (epoch !== null && (epoch !== (status.user && status.user.epoch) || previousId !== (status.user && status.user.id))) {
    clearEvidence(); el("status").textContent = "身份或权限已变化，已清除当前证据与回答，请重新查询。";
  }
  me=status.user; csrf=status.csrf || ""; epoch=me ? me.epoch : null;
  el("identity").textContent = me ? `${me.name} · ${me.role} · 权限版本 ${me.epoch}` : status.oidc_configured ? "尚未登录" : "OIDC 尚未配置；受保护业务不可访问";
  el("login").hidden=!!me || !status.oidc_configured; el("logout").hidden=!me;
  el("admin").hidden=!me || me.role!=="admin";
  el("auditpanel").hidden=!me || !["admin","compliance"].includes(me.role);
  for (const id of ["search","ask","corpus","mode","question"]) el(id).disabled=!me;
  if (me && (previousId !== me.id || !el("corpus").options.length)) await loadCorpora();
  return status;
}
async function loadCorpora() {
  const corpora=await api("/api/corpora"); const selected=el("corpus").value; el("corpus").replaceChildren();
  for (const corpus of corpora) option(el("corpus"), corpus.id, corpus.label);
  if (corpora.some(c=>c.id===selected)) el("corpus").value=selected;
  if (!corpora.length) el("status").textContent="账号尚未绑定可用来源身份，请联系管理员。";
}
function renderHits(hits) {
  el("hits").replaceChildren();
  for (const hit of hits) {
    const card=document.createElement("article"); card.className="hit";
    const title=document.createElement("h2"); title.textContent=`${hit.citation_id ? `[${hit.citation_id}] ` : ""}${hit.title}`;
    const meta=document.createElement("p"); meta.className="muted"; meta.textContent=`${hit.source} · ${hit.version} · ${hit.acl_basis} · 来源时间 ${hit.ts || "未知"} · 索引 ${hit.indexed_at}`;
    const text=document.createElement("p"); text.textContent=hit.excerpt || hit.snippet;
    card.append(title,meta,text); card.addEventListener("click",()=>openDoc(hit.corpus,hit.doc_id)); el("hits").append(card);
  }
}
async function query(ask) {
  clearEvidence(); const current=generation; el("status").textContent=ask ? "正在检索授权证据并生成回答…" : "正在检索…";
  try {
    if (!el("corpus").value) throw new Error("请先绑定来源身份。");
    const params={corpus:el("corpus").value,q:el("question").value,mode:el("mode").value};
    const result=ask ? await api("/api/ask",params) : await api(`/api/search?${new URLSearchParams(params)}`);
    if (current!==generation) return;
    if (ask) { el("answer").hidden=false; el("answer").textContent=result.answer; }
    renderHits(result.evidence || result.hits || []);
    el("status").textContent=`${result.provider || result.mode} · 请求 ${result.request_id} · 证据 ${(result.evidence || result.hits || []).length} 条`;
  } catch(error) { if (current===generation || !el("status").textContent) el("status").textContent=error.message; }
}
async function openDoc(corpus,doc_id) {
  const current=generation;
  try {
    const payload=await api(`/api/doc?${new URLSearchParams({corpus,doc_id})}`);
    if (current!==generation) return;
    const doc=payload.doc; el("reader").replaceChildren(); el("reader").hidden=false;
    const heading=document.createElement("h2"); heading.textContent=doc.title; el("reader").append(heading);
    const text=document.createElement("p"); text.textContent=doc.text; el("reader").append(text);
    if (doc.source_url) { try { const url=new URL(doc.source_url); if (["https:","http:"].includes(url.protocol)) { const link=document.createElement("a"); link.href=url.href; link.textContent="查看来源链接／导出文件"; link.target="_blank"; link.rel="noopener noreferrer"; el("reader").append(link); } } catch {} }
  } catch(error) { el("status").textContent=error.message; }
}
async function loadAdmin() {
  if (!me || me.role!=="admin") return;
  const selected=el("target").value;
  [people,principals]=await Promise.all([api("/api/admin/users"),api("/api/admin/principals")]);
  el("target").replaceChildren(); for(const p of people) option(el("target"),p.id,`${p.name} · ${p.role} · ${p.enabled ? "启用" : "停用"}`);
  if(people.some(p=>p.id===selected)) el("target").value=selected;
  el("binding").replaceChildren(); for(const p of principals) option(el("binding"),p.principal_id,`${p.corpus} · ${p.name} · ${p.role}`);
  showPermissions();
}
function showPermissions() {
  const person=people.find(p=>p.id===el("target").value);
  el("permissions").textContent=person ? JSON.stringify({bindings:person.bindings,restrictions:person.restrictions},null,2) : "";
  if(person) { el("role").value=person.role; el("clearance").value=person.clearance; }
}
async function mutate(fields) {
  try { await api("/api/admin/permissions",{user_id:el("target").value,...fields}); clearEvidence(); await sessionStatus(); await loadCorpora(); await loadAdmin(); el("adminstatus").textContent="已持久化。下一次请求与交付检查使用新权限。"; }
  catch(error) { el("adminstatus").textContent=error.message; }
}
function binding(enabled) { const p=principals.find(p=>p.principal_id===el("binding").value); if(p) return mutate({action:"binding",corpus:p.corpus,principal_id:p.principal_id,enabled}); }
function restrict(denied) { const p=principals.find(p=>p.principal_id===el("binding").value); if(p) return mutate({action:"restriction",corpus:p.corpus,kind:el("rulekind").value,value:el("rulevalue").value,denied}); }
el("search").onclick=()=>query(false); el("ask").onclick=()=>query(true);
el("corpus").onchange=clearEvidence; el("mode").onchange=clearEvidence;
el("logout").onclick=async()=>{ await api("/api/logout",{}); clearEvidence(); el("corpus").replaceChildren(); await sessionStatus(); };
el("target").onchange=showPermissions;
el("bind").onclick=()=>binding(true); el("unbind").onclick=()=>binding(false);
el("deny").onclick=()=>restrict(true); el("restore").onclick=()=>restrict(false);
el("saveaccount").onclick=()=>mutate({action:"account",role:el("role").value,clearance:Number(el("clearance").value)});
el("disable").onclick=()=>mutate({action:"account",enabled:false}); el("enable").onclick=()=>mutate({action:"account",enabled:true});
el("auditgo").onclick=async()=>{ try { auditData=await api(`/api/audit?${new URLSearchParams({q:el("auditquestion").value})}`); el("auditresults").textContent=JSON.stringify(auditData,null,2); el("auditexport").disabled=false; } catch(error) { el("auditresults").textContent=error.message; } };
el("auditexport").onclick=()=>{ if(!auditData)return; const url=URL.createObjectURL(new Blob([JSON.stringify(auditData,null,2)],{type:"application/json"})); const a=document.createElement("a"); a.href=url;a.download="contextledger-audit-redacted.json";a.click();URL.revokeObjectURL(url); };
sessionStatus().then(loadAdmin).catch(error=>{el("identity").textContent=error.message;});
setInterval(()=>sessionStatus().catch(()=>{clearEvidence();el("status").textContent="连接不可用，已清除当前展示。";}),5000);
document.addEventListener("visibilitychange",()=>{if(document.hidden)clearEvidence();else sessionStatus().catch(()=>clearEvidence());});
