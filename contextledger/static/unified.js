// ContextLedger Frontend Integration

// State
let currentUser = null;
let currentCsrf = null;
let currentEpoch = null;
let isDemoMode = document.body.dataset.demoMode === 'true';
let requestGeneration = 0;
let queryBusy = false;
let identityBusy = false;
let adminPeople = [];
let adminPrincipals = [];
let securityBaseline = null;
let securitySelectedId = null;
let auditData = null;
let auditBusy = false;
let plannerConfigured = false;
let plannerSettingLoaded = false;

// DOM Elements
const els = {
  navTabs: document.querySelectorAll('.nav-tab'),
  navAudit: document.getElementById('nav-audit'),
  navAdmin: document.getElementById('nav-admin'),
  views: document.querySelectorAll('.view-panel'),
  identity: document.getElementById('current-identity'),
  demoSelect: document.getElementById('demo-account-select'),
  loginBtn: document.getElementById('login-btn'),
  logoutBtn: document.getElementById('logout-btn'),

  datasetSelect: document.getElementById('dataset-select'),
  queryInput: document.getElementById('query-input'),
  queryValidation: document.getElementById('query-validation'),
  btnAsk: document.getElementById('btn-ask'),
  btnSearch: document.getElementById('btn-search'),
  modeRadios: document.getElementsByName('search_mode'),
  planningToggle: document.getElementById('planning-toggle'),
  plannerAvailability: document.getElementById('planner-availability'),

  stateOnboarding: document.getElementById('onboarding-state'),
  stateLoading: document.getElementById('loading-state'),
  loadingText: document.getElementById('loading-text'),
  stateError: document.getElementById('error-state'),
  errorTitle: document.getElementById('error-title'),
  errorMessage: document.getElementById('error-message'),

  stateResults: document.getElementById('results-state'),
  resultStatus: document.getElementById('result-status'),
  workspaceGrid: document.getElementById('workspace-grid'),
  homeSupport: document.getElementById('home-support'),
  homePermissionVersion: document.getElementById('home-permission-version'),
  homeCorpusCount: document.getElementById('home-corpus-count'),
  querySummary: document.getElementById('query-summary-text'),
  securityName: document.getElementById('security-summary-name'),
  securityRole: document.getElementById('security-summary-role'),
  securityEpoch: document.getElementById('security-summary-epoch'),
  securityEvidence: document.getElementById('security-summary-evidence'),
  queryPlanStatus: document.getElementById('query-plan-status'),
  answerBox: document.getElementById('answer-box'),
  evidenceList: document.getElementById('evidence-list'),

  docReader: document.getElementById('document-reader'),
  docTitle: document.getElementById('doc-title'),
  docContent: document.getElementById('doc-content'),
  docMetadata: document.getElementById('doc-metadata'),
  docSourceLink: document.getElementById('doc-source-link'),
  btnCloseDoc: document.getElementById('btn-close-doc'),
  btnCloseDocSecondary: document.getElementById('btn-close-doc-secondary'),
  securityDemoGuide: document.getElementById('security-demo-guide'),

  adminForm: document.getElementById('admin-mutate-form'),
  adminFeedback: document.getElementById('admin-mutate-feedback'),
  btnLoadUsers: document.getElementById('btn-load-users'),
  adminUsersList: document.getElementById('admin-users-list'),
  auditForm: document.getElementById('audit-form'),
  auditSearch: document.getElementById('audit-search'),
  auditAsk: document.getElementById('audit-ask'),
  auditAnswer: document.getElementById('audit-answer'),
  auditResults: document.getElementById('audit-results'),
  auditExport: document.getElementById('audit-export')
};

// 1. Core API Wrapper
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const isPost = options.method && options.method.toUpperCase() === 'POST';

  if (isPost) {
    headers.set('Content-Type', 'application/json');
    if (currentCsrf) headers.set('X-CSRF-Token', currentCsrf);
  }

  try {
    const res = await fetch(path, {
      ...options,
      headers,
      credentials: 'same-origin',
      cache: 'no-store'
    });

    if (res.status === 401 || res.status === 403 || res.status === 409) {
      clearEvidence();
    }

    if (!res.ok) {
      let errData = {};
      try { errData = await res.json(); } catch(e) {}

      let msg = 'An unexpected error occurred.';
      if (res.status === 400) msg = 'Check the request and try again.';
      if (res.status === 401) msg = 'Unauthorised. Please log in.';
      if (res.status === 403) msg = 'Access denied. You lack permission for this action.';
      if (res.status === 409) msg = 'Data snapshot or permissions changed. Please submit your query again.';
      if (res.status === 503) msg = 'Service temporarily unavailable. Please try again later.';
      if (res.status === 404) msg = 'Resource not found.';

      throw { status: res.status, message: msg };
    }

    return await res.json();
  } catch (error) {
    if (!error.status) throw { status: 0, message: 'Network or connectivity error.' };
    throw error;
  }
}

// 2. Session Management
async function sessionStatus() {
  try {
    const data = await api('/api/session');
    const oldUserId = currentUser?.id;
    const oldEpoch = currentEpoch;

    currentUser = data.user;
    currentCsrf = data.csrf;
    plannerConfigured = Boolean(data.workflows?.planner_configured);
    if (!plannerSettingLoaded && data.workflows) {
      els.planningToggle.checked = plannerConfigured && Boolean(data.workflows.planner_enabled);
      plannerSettingLoaded = true;
    }
    if (!plannerConfigured) els.planningToggle.checked = false;
    els.plannerAvailability.textContent = plannerConfigured
      ? 'Optional. The original question remains in the search plan.'
      : 'Planner unavailable in this preview. Search uses the original question.';

    if (currentUser) {
      currentEpoch = currentUser.epoch;
      els.identity.textContent = `${isDemoMode ? 'Demo identity · ' : ''}${currentUser.name} (${currentUser.role})`;
      if (els.securityName) els.securityName.textContent = currentUser.name;
      if (els.securityRole) els.securityRole.textContent = currentUser.role;
      if (els.securityEpoch) els.securityEpoch.textContent = currentUser.epoch ?? '—';
      if (els.homePermissionVersion) els.homePermissionVersion.textContent = currentUser.epoch ?? '—';
      if (els.logoutBtn) els.logoutBtn.classList.remove('hidden');
      if (els.loginBtn) els.loginBtn.classList.add('hidden');

      applyRolePermissions(currentUser.role);
      els.securityDemoGuide?.classList.toggle('hidden', !isDemoMode || currentUser.role !== 'admin');
    } else {
      currentEpoch = null;
      if (els.homePermissionVersion) els.homePermissionVersion.textContent = '—';
      els.identity.textContent = isDemoMode ? 'Select a demo identity' : 'Not signed in';
      if (els.logoutBtn) els.logoutBtn.classList.add('hidden');
      if (els.loginBtn) els.loginBtn.classList.remove('hidden');
      applyRolePermissions('none');
      els.securityDemoGuide?.classList.add('hidden');
    }

    // Protection: clear if identity or epoch changes
    if (oldUserId !== currentUser?.id || oldEpoch !== currentEpoch) {
      clearEvidence();
      await loadCorpora();
    }
    setQueryControls();
    setAuditControls();
  } catch (err) {
    els.identity.textContent = 'Session error';
    currentUser = null;
    currentEpoch = null;
    currentCsrf = null;
    plannerConfigured = false;
    els.planningToggle.checked = false;
    els.plannerAvailability.textContent = 'Planner availability could not be checked.';
    clearEvidence();
    await loadCorpora();
    setQueryControls();
    setAuditControls();
  }
}

function setQueryControls() {
  const disabled = !currentUser || queryBusy || identityBusy;
  if (els.demoSelect) els.demoSelect.disabled = identityBusy;
  for (const control of [els.datasetSelect, els.queryInput, els.btnAsk, els.btnSearch, ...els.modeRadios]) {
    if (control) control.disabled = disabled;
  }
  els.planningToggle.disabled = disabled || !plannerConfigured;
}

function setAuditControls() {
  const allowed = currentUser && ['admin', 'compliance'].includes(currentUser.role);
  els.auditSearch.disabled = auditBusy || !allowed;
  els.auditAsk.disabled = auditBusy || !allowed;
  els.auditExport.disabled = auditBusy || !allowed || !auditData;
}

function applyRolePermissions(role) {
  els.navAudit.classList.toggle('hidden', role !== 'compliance' && role !== 'admin');
  els.navAdmin.classList.toggle('hidden', role !== 'admin');
  const activeTab = document.querySelector('.nav-tab.active');
  if (activeTab?.classList.contains('hidden')) {
    for (const tab of els.navTabs) tab.classList.toggle('active', tab.dataset.view === 'workspace');
    for (const view of els.views) {
      const active = view.id === 'view-workspace';
      view.classList.toggle('active', active);
      view.classList.toggle('hidden', !active);
    }
    document.getElementById('current-view-label').textContent = 'Workspace';
  }
}

// 3. Setup Initial Data
async function loadDemoAccounts() {
  if (!isDemoMode || !els.demoSelect) return [];
  try {
    const accounts = await api('/api/demo/accounts');
    els.demoSelect.innerHTML = '<option value="" disabled selected>Switch demo account...</option>';
    accounts.forEach(acc => {
      const opt = document.createElement('option');
      opt.value = acc.id;
      opt.textContent = `${acc.name} (${acc.role})`;
      if (!acc.enabled) opt.disabled = true;
      els.demoSelect.appendChild(opt);
    });
    if (currentUser && accounts.some(acc => acc.id === currentUser.id)) {
      els.demoSelect.value = currentUser.id;
    }
    return accounts;
  } catch (e) {
    console.error('Failed to load demo accounts', e);
    return [];
  }
}

async function selectDemoAccount(userId) {
  if (identityBusy) return;
  identityBusy = true;
  setQueryControls();
  try {
    await api('/api/demo/select', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId })
    });
    clearEvidence();
    await sessionStatus();
    await loadCorpora();
    if (currentUser) els.demoSelect.value = currentUser.id;
  } catch (e) {
    showError('Demo Selection Failed', e.message);
  } finally {
    identityBusy = false;
    setQueryControls();
  }
}

async function loadCorpora() {
  const previous = els.datasetSelect.value;
  els.datasetSelect.innerHTML = '<option value="" disabled selected>Select a dataset...</option>';
  if (els.homeCorpusCount) els.homeCorpusCount.textContent = currentUser ? '0' : '—';
  if (!currentUser) return;

  try {
    const corpora = await api('/api/corpora');
    corpora.forEach(c => {
      const opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = c.label;
      els.datasetSelect.appendChild(opt);
    });
    if (els.homeCorpusCount) els.homeCorpusCount.textContent = String(corpora.length);
    if (corpora.some(c => c.id === previous)) els.datasetSelect.value = previous;
    else if (corpora.length === 1) els.datasetSelect.value = corpora[0].id;
    if (!corpora.length) {
      showError('No dataset access', currentUser?.role === 'admin'
        ? 'This admin account has no business-document access. Use the Admin or Audit view, or choose an employee demo identity.'
        : 'This account is not bound to a dataset. Contact an administrator.');
    }
  } catch (e) {
    console.error('Failed to load corpora', e);
  }
}

// 4. Evidence & UI Reset
function clearEvidence() {
  requestGeneration++;
  if (els.docReader.open) els.docReader.close();
  const radar = document.getElementById("radar");
  radar.classList.add("hidden");
  radar.open = false;
  const fullAnswer = document.querySelector('.full-answer');
  if (fullAnswer) fullAnswer.open = false;
  for (const id of ["radarcoverage", "radarconflicts", "radartimeline", "radar-summary-citations", "radar-needs-list"]) document.getElementById(id).replaceChildren();
  document.getElementById("radar-presentation").classList.add("hidden");
  document.getElementById("radar-needs").classList.add("hidden");
  els.answerBox.textContent = '';
  els.answerBox.classList.add('hidden');
  els.evidenceList.innerHTML = '';
  els.docContent.textContent = '';
  els.docTitle.textContent = 'Document View';
  els.docSourceLink.classList.add('hidden');
  els.docSourceLink.removeAttribute('href');
  els.resultStatus.textContent = '';
  els.queryValidation?.classList.add('hidden');
  if (els.queryValidation) els.queryValidation.textContent = '';
  els.queryPlanStatus.textContent = '';
  els.queryPlanStatus.classList.add('hidden');
  if (els.adminUsersList) els.adminUsersList.textContent = '';
  if (els.adminFeedback) els.adminFeedback.textContent = '';

  if (currentUser) showState(els.stateOnboarding);
  else showError('Select an identity', isDemoMode ? 'Choose a demo identity to start.' : 'Sign in to search authorised evidence.');
  if (els.auditResults) els.auditResults.textContent = '';
  els.auditAnswer.textContent = '';
  els.auditAnswer.classList.add('hidden');
  auditData = null;
  setAuditControls();
}

function showState(elementToShow) {
  [els.stateOnboarding, els.stateLoading, els.stateError, els.stateResults].forEach(el => {
    el.classList.add('hidden');
  });
  if (elementToShow) elementToShow.classList.remove('hidden');
  const resultScreen = [els.stateLoading, els.stateError, els.stateResults].includes(elementToShow);
  els.workspaceGrid?.classList.toggle('has-results', resultScreen);
  els.homeSupport?.classList.toggle('hidden', resultScreen);
  if (resultScreen && els.querySummary) els.querySummary.textContent = els.queryInput.value.trim();
}

function showError(title, msg) {
  els.errorTitle.textContent = title;
  els.errorMessage.textContent = msg;
  showState(els.stateError);
}

// 5. Query execution
function getSearchMode() {
  for (const radio of els.modeRadios) {
    if (radio.checked) return radio.value;
  }
  return 'hybrid';
}

async function query(ask) {
  if (queryBusy || !currentUser) return;
  const corpus = els.datasetSelect.value;
  const q = els.queryInput.value.trim();
  const mode = getSearchMode();
  const planning = plannerConfigured && els.planningToggle.checked;

  if (!corpus || !q) {
    els.queryValidation.textContent = !corpus ? 'Select a dataset to continue.' : 'Enter a question to continue.';
    els.queryValidation.classList.remove('hidden');
    (!corpus ? els.datasetSelect : els.queryInput).focus();
    return;
  }
  els.queryValidation.classList.add('hidden');

  clearEvidence();
  const generation = requestGeneration;
  queryBusy = true;
  setQueryControls();
  showState(els.stateLoading);
  els.loadingText.textContent = planning
    ? ask ? 'Planning, retrieving evidence, and generating an answer…' : 'Planning and searching authorised evidence…'
    : ask ? 'Retrieving evidence and generating an answer…' : 'Searching authorised evidence…';

  try {
    let data;
    if (ask) {
      data = await api('/api/ask', {
        method: 'POST',
        body: JSON.stringify({ corpus, q, mode, planning })
      });
    } else {
      const params = new URLSearchParams({ corpus, q, mode, planning: String(planning) });
      data = await api(`/api/search?${params.toString()}`);
    }

    if (generation !== requestGeneration) return;

    renderResults(data, ask);

  } catch (e) {
    if (generation === requestGeneration) showError('Request Failed', e.message);
  } finally {
    queryBusy = false;
    setQueryControls();
  }
}

// 6. Rendering Results
function renderResults(data, asked) {
  showState(els.stateResults);
  const fullAnswer = document.querySelector('.full-answer');
  fullAnswer?.classList.toggle('hidden', !(asked && data.answer));
  const items = data.evidence || data.hits || [];
  if (els.securityEvidence) els.securityEvidence.textContent = `${items.length} authorised record${items.length === 1 ? '' : 's'}`;
  els.resultStatus.textContent = asked
    ? data.provider === 'mock_fallback' ? 'No reliable answer was generated. Authorised evidence remains below.'
      : data.decision === 'clarification_required' ? 'Clarification needed before answering.'
      : data.decision === 'insufficient' ? 'Authorised evidence is insufficient for a reliable answer.'
      : data.provider === 'mock' ? 'Deterministic demo answer' : 'Answer generated'
    : data.query_plan?.status === 'clarification_required' ? 'Clarification needed before searching.'
      : items.length ? `${items.length} authorised evidence item${items.length === 1 ? '' : 's'}` : 'No authorised evidence found.';
  renderQueryPlan(data.query_plan);

  if (asked && data.answer) {
    els.answerBox.textContent = data.answer;
    els.answerBox.classList.remove('hidden');
  } else {
    els.answerBox.classList.add('hidden');
  }

  renderHits(items, data.request_id);
  if (asked) renderRadar(data.radar, items, data.radar_presentation);
}

function citationButton(id, evidence) {
  const item = evidence.find(hit => hit.citation_id === id);
  if (!item) return null;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'citation-ref';
  button.textContent = `[${id}]`;
  button.setAttribute('aria-label', `Open evidence ${id}`);
  button.addEventListener('click', () => openDoc(item.corpus || els.datasetSelect.value, item.doc_id, item.title));
  return button;
}

function renderRadar(radar, evidence, presentation) {
  if (!radar) return;
  const el = id => document.getElementById(id);
  el("radar").classList.remove("hidden");
  el("radar").open = true;
  el("radarconflicts").replaceChildren();
  el("radartimeline").replaceChildren();
  const coverage=radar.coverage;
  const reasonLabels={document_limit:"document limit",related_scan_limit:"related search limit",expansion_round_limit:"expansion round limit",relation_limit:"relationship limit",time_budget:"time budget"};
  const reasons=(coverage.truncation_reasons || []).map(r=>reasonLabels[r] || "search scope limit");
  if(coverage.evidence_excerpts_truncated || coverage.model_input_truncated) reasons.push("evidence excerpt limit");
  el("radarcoverage").textContent=`${coverage.documents} authorised records in this selection${reasons.length ? ` · Limited by ${reasons.join(", ")}` : ""}. Event times marked unknown remain unknown.`;

  const presentationBox = el("radar-presentation");
  presentationBox.classList.toggle("hidden", !presentation);
  el("radar-needs").classList.toggle("hidden", !presentation || presentation.status !== "pending_confirmation");
  if (presentation) {
    el("radar-status").textContent = presentation.status === "confirmed" ? "Confirmed" : "Pending confirmation";
    el("radar-status").className = `status-pill ${presentation.status === "confirmed" ? "status-confirmed" : "status-pending"}`;
    el("radar-headline").textContent = presentation.headline;
    el("radar-explanation").textContent = presentation.explanation;
    for (const id of presentation.citation_ids) {
      const button = citationButton(id, evidence);
      if (button) el("radar-summary-citations").append(button);
    }
    for (const item of presentation.needs_confirmation) {
      const li = document.createElement("li");
      const text = document.createElement("span");
      text.textContent = item.item;
      li.append(text);
      for (const id of item.citation_ids) {
        const button = citationButton(id, evidence);
        if (button) li.append(button);
      }
      el("radar-needs-list").append(li);
    }
  }
  for (const conflict of radar.disagreements) {
    const card=document.createElement("div"); card.className="radar-conflict";
    const title=document.createElement("strong"); title.textContent=`Conflicting reports · ${conflict.entity_id} · ${conflict.attribute.replaceAll("_", " ")}`;
    const detail=document.createElement("p"); detail.textContent="Different reported values need review against their time and scope.";
    card.append(title,detail);
    for (const claim of conflict.claims) {
      const row=document.createElement("div"); row.className="conflict-claim";
      row.textContent=`${claim.value} · `;
      const quote=document.createElement("span"); quote.textContent=claim.quote;
      row.append(quote);
      const button=citationButton(claim.citation_id,evidence); if(button) row.append(button);
      card.append(row);
    }
    el("radarconflicts").append(card);
  }
  for (const event of radar.event_candidates) {
    const li=document.createElement("li"); li.className="radar-event"; const item=evidence.find(e=>e.citation_id===event.citation_id);
    const status=radar.source_statuses.find(s=>s.citation_id===event.citation_id);
    const labels={native_state:"Source system state",comment:"Comment / review",description:"Source description",artifact:"Source record"};
    const label=labels[event.type] || "Source record";
    const button=document.createElement("button"); button.type="button"; button.className="radarlink";
    button.textContent=`${event.event_time || "Event time unknown"} · ${label}${status && status.native_status ? ` · ${status.native_status}` : ""} · ${event.historical ? "Historical revision · " : ""}${item ? item.title : event.doc_id}`;
    if(item) button.onclick=()=>openDoc(item.corpus,item.doc_id);
    const quote=document.createElement("p"); quote.textContent=(event.historical ? `该修订观测于：${event.observed_at || "未知"}\n` : "") + event.quote;
    const citation=citationButton(event.citation_id,evidence);
    li.append(button,quote); if(citation) li.querySelector("button.radarlink").after(citation); el("radartimeline").append(li);
  }
}

function renderQueryPlan(plan) {
  if (!plan) {
    els.queryPlanStatus.textContent = '';
    els.queryPlanStatus.classList.add('hidden');
    return;
  }
  const descriptions = {
    disabled: 'Query planning was off. The original question was searched.',
    not_configured: 'Planner was unavailable. The original question was searched.',
    api_unavailable: 'Planner did not respond. The original question was searched.',
    invalid_output: 'Planner output was rejected. The original question was searched.',
    clarification_required: 'The planner requests clarification; it did not change your question.',
    skipped: 'Planning was skipped because no business evidence was available.'
  };
  const status = descriptions[plan.status] || `Planner status: ${String(plan.status || 'unknown').replaceAll('_', ' ')}.`;
  const branches = Number.isInteger(plan.branch_count)
    ? ` ${plan.branch_count} authorised retrieval branch${plan.branch_count === 1 ? '' : 'es'} considered.` : '';
  els.queryPlanStatus.textContent = status + branches;
  els.queryPlanStatus.classList.remove('hidden');
}

function renderHits(hits, requestId) {
  els.evidenceList.innerHTML = '';

  if (requestId) {
    const reqDiv = document.createElement('div');
    reqDiv.className = 'request-id';
    reqDiv.textContent = `Req ID: ${requestId}`;
    els.evidenceList.appendChild(reqDiv);
  }

  hits.forEach((hit, idx) => {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'evidence-card';

    // Header row: Title + Citation ID
    const header = document.createElement('div');
    header.className = 'ev-header';

    const title = document.createElement('div');
    title.className = 'ev-title';
    title.textContent = hit.title || `Document ${hit.doc_id}`;

    const cit = document.createElement('div');
    cit.className = 'ev-citation';
    cit.textContent = `[${hit.citation_id || idx + 1}]`;

    header.appendChild(title);
    header.appendChild(cit);

    // Meta row: source / version / time
    const meta = document.createElement('div');
    meta.className = 'ev-meta';
    meta.textContent = `${hit.source || 'Unknown source'} · Version ${hit.version || 'unknown'} · Source time ${hit.ts || 'unknown'} · Indexed ${hit.indexed_at || 'unknown'}`;

    // Access / Snippet
    const access = document.createElement('div');
    access.className = 'ev-access';
    access.textContent = hit.excerpt || hit.snippet || 'No excerpt available.';
    const basis = document.createElement('div');
    basis.className = 'ev-basis';
    basis.textContent = `Access: ${hit.acl_basis || 'authorised by current session'} · Source check: ${hit.source_check || 'unknown'}`;

    card.appendChild(header);
    card.appendChild(meta);
    card.appendChild(access);
    card.appendChild(basis);

    card.addEventListener('click', () => {
      openDoc(hit.corpus || els.datasetSelect.value, hit.doc_id, title.textContent);
    });

    els.evidenceList.appendChild(card);
  });
}

// 7. Document Reader
async function openDoc(corpus, doc_id, titleText) {
  const generation = requestGeneration;
  els.docTitle.textContent = titleText || 'Loading evidence…';
  els.docContent.textContent = 'Loading original document…';
  els.docMetadata.replaceChildren();
  if (!els.docReader.open) els.docReader.showModal();

  try {
    const params = new URLSearchParams({ corpus, doc_id });
    const data = await api(`/api/doc?${params.toString()}`);
    if (generation !== requestGeneration) return;

    if (data.available && data.doc) {
      els.docTitle.textContent = data.doc.title || titleText || `Document ${doc_id}`;
      els.docContent.textContent = data.doc.text || 'No text available.';
      els.docSourceLink.classList.add('hidden');
      els.docSourceLink.removeAttribute('href');
      if (data.doc.source_url) {
        try {
          const url = new URL(data.doc.source_url);
          if (url.protocol === 'https:' || url.protocol === 'http:') {
            els.docSourceLink.href = url.href;
            els.docSourceLink.classList.remove('hidden');
          }
        } catch (_) {}
      }
      const fields = [
        ['Source', data.doc.source], ['Version', data.doc.version],
        ['Source time', data.doc.ts || 'Unknown'], ['Indexed at', data.doc.indexed_at || 'Unknown'],
        ['Access basis', data.doc.acl_basis || 'Current authorised session'],
        ['Source status', data.doc.source_check || 'Unknown'],
        ['Content fingerprint', data.doc.content_hash || 'Unavailable']
      ];
      for (const [label, value] of fields) {
        const row = document.createElement('div'); row.className = 'passport-meta-row';
        const key = document.createElement('span'); key.textContent = label;
        const content = document.createElement('span'); content.textContent = value;
        if (label === 'Content fingerprint') content.classList.add('hash-value');
        row.append(key, content); els.docMetadata.append(row);
      }
      els.docContent.textContent = data.doc.text || 'No text available.';
    } else {
      els.docReader.close();
      showError('Not Available', 'The original document is not available in the snapshot.');
    }
  } catch (e) {
    if (generation === requestGeneration) { if (els.docReader.open) els.docReader.close(); showError('Document Error', e.message); }
  }
}

// 8. Admin / Audit functions
async function loadAdmin() {
  if (currentUser?.role !== 'admin') return;
  try {
    els.adminUsersList.textContent = 'Loading users...';
    [adminPeople, adminPrincipals] = await Promise.all([
      api('/api/admin/users'), api('/api/admin/principals')
    ]);
    const target = document.getElementById('admin-user-id');
    const selected = target.value;
    target.replaceChildren();
    addOption(target, '', 'Choose an account');
    for (const person of adminPeople) addOption(target, person.id, `${person.name} · ${person.role}`);
    if (adminPeople.some(person => person.id === selected)) target.value = selected;
    else {
      const defaultEmployee = adminPeople.find(person => person.enabled && person.role === 'member');
      if (defaultEmployee) target.value = defaultEmployee.id;
    }

    const principal = document.getElementById('admin-principal');
    const selectedPrincipal = principal.value;
    principal.replaceChildren();
    addOption(principal, '', 'Choose a source identity');
    for (const item of adminPrincipals) addOption(principal, JSON.stringify([item.corpus, item.principal_id]),
      `${item.corpus} · ${item.name || item.principal_id}`);
    if ([...principal.options].some(option => option.value === selectedPrincipal)) principal.value = selectedPrincipal;

    const corpus = document.getElementById('admin-corpus');
    const selectedCorpus = corpus.value;
    corpus.replaceChildren();
    addOption(corpus, '', 'Choose a dataset');
    for (const name of [...new Set(adminPrincipals.map(item => item.corpus))]) addOption(corpus, name, name);
    if ([...corpus.options].some(option => option.value === selectedCorpus)) corpus.value = selectedCorpus;

    renderAdminUsers();
    syncAdminSelected();
  } catch (e) {
    els.adminUsersList.textContent = 'Failed to load users: ' + e.message;
  }
}

function addOption(select, value, label) {
  const option = document.createElement('option');
  option.value = value;
  option.textContent = label;
  select.appendChild(option);
}

function renderAdminUsers() {
  els.adminUsersList.replaceChildren();
  if (!adminPeople.length) {
    els.adminUsersList.textContent = 'No accounts are available.';
    return;
  }
  for (const person of adminPeople) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'admin-user-row';
    const summary = document.createElement('span');
    summary.className = 'admin-user-summary';
    const name = document.createElement('strong');
    name.textContent = person.name;
    const role = document.createElement('small');
    role.textContent = `${person.role} · ${person.enabled ? 'Enabled' : 'Disabled'}`;
    summary.append(name, role);
    const detail = document.createElement('span');
    detail.className = 'admin-user-detail';
    detail.textContent = `${(person.bindings || []).filter(item => item.enabled).length} bindings · ${(person.restrictions || []).length} restrictions`;
    row.append(summary, detail);
    row.addEventListener('click', () => {
      document.getElementById('admin-user-id').value = person.id;
      syncAdminSelected();
    });
    els.adminUsersList.appendChild(row);
  }
}

function syncAdminSelected() {
  const person = adminPeople.find(item => item.id === document.getElementById('admin-user-id').value);
  if (!person) return;
  if (securitySelectedId !== person.id) {
    securitySelectedId = person.id;
    securityBaseline = structuredClone(person);
  }
  document.getElementById('admin-role').value = person.role;
  document.getElementById('admin-clearance').value = String(person.clearance ?? 1);
  document.getElementById('admin-enabled').value = String(Boolean(person.enabled));
  const binding = (person.bindings || []).find(item => item.enabled) || (person.bindings || [])[0];
  if (binding) document.getElementById('admin-principal').value = JSON.stringify([binding.corpus, binding.principal_id]);
  const restriction = (person.restrictions || [])[0];
  if (restriction) {
    document.getElementById('admin-corpus').value = restriction.corpus;
    document.getElementById('admin-rule-kind').value = restriction.kind;
    document.getElementById('admin-rule-value').value = restriction.value;
  }
  renderSecurityStates(person);
}

function renderSecurityStates(person) {
  const before = securityBaseline || person;
  const labelFor = binding => {
    const source = adminPrincipals.find(item => item.corpus === binding.corpus && item.principal_id === binding.principal_id);
    return `${binding.corpus} · ${source?.name || binding.principal_id}`;
  };
  const renderBindings = (id, user) => {
    const list = document.getElementById(id);
    const bindings = user?.bindings || [];
    const active = bindings.filter(binding => binding.enabled);
    document.getElementById(id.replace('-bindings', '-count')).textContent = String(active.length);
    list.replaceChildren();
    if (!bindings.length) {
      const empty = document.createElement('li');
      empty.textContent = 'No source bindings are recorded for this account.';
      list.appendChild(empty);
      return;
    }
    for (const binding of bindings) {
      const row = document.createElement('li');
      row.className = binding.enabled ? '' : 'is-revoked';
      const name = document.createElement('span');
      name.textContent = labelFor(binding);
      const state = document.createElement('strong');
      state.textContent = binding.enabled ? 'Active' : 'Revoked';
      row.append(name, state);
      list.appendChild(row);
    }
  };
  renderBindings('security-before-bindings', before);
  renderBindings('security-after-bindings', person);
  document.getElementById('security-before-version').textContent = String(before.epoch ?? '—');
  document.getElementById('security-after-version').textContent = String(person.epoch ?? '—');
  document.getElementById('security-current-version').textContent = String(person.epoch ?? '—');
  const queryAgain = document.getElementById('security-run-query');
  if (queryAgain) queryAgain.disabled = !isDemoMode || !person.enabled || person.role !== 'member';
}

async function queryAsSelectedEmployee() {
  const person = adminPeople.find(item => item.id === document.getElementById('admin-user-id').value);
  if (!person || !isDemoMode || !person.enabled) return;
  try {
    if (currentUser?.id !== person.id) await selectDemoAccount(person.id);
    const workspaceTab = [...els.navTabs].find(tab => tab.dataset.view === 'workspace');
    workspaceTab?.click();
    if (!els.datasetSelect.value && els.datasetSelect.options.length > 1) els.datasetSelect.selectedIndex = 1;
    els.queryInput.value = 'Has SG Batch Payments v2.3 fully recovered?';
    await query(true);
  } catch (error) {
    els.adminFeedback.className = 'feedback-msg is-error';
    els.adminFeedback.textContent = 'Could not run the employee query: ' + (error.message || 'request failed');
  }
}

function updateAdminAction() {
  const action = document.getElementById('admin-action').value;
  for (const kind of ['binding', 'restriction', 'account']) {
    document.getElementById(`admin-${kind}-fields`).classList.toggle('hidden', kind !== action);
  }
}

function renderAudit(data) {
  els.auditResults.replaceChildren();
  const events = Array.isArray(data.events) ? data.events : [];
  const summary = document.createElement('div');
  summary.className = 'audit-summary';
  const integrity = data.integrity?.valid === true ? 'Local audit chain · valid' : 'Audit integrity needs review';
  summary.textContent = events.length + ' event' + (events.length === 1 ? '' : 's') + ' in this filtered selection · ' + integrity;
  els.auditResults.appendChild(summary);
  if (!events.length) {
    const empty = document.createElement('p');
    empty.className = 'audit-empty';
    empty.textContent = 'No matching events were returned.';
    els.auditResults.appendChild(empty);
  }
  const list = document.createElement('div'); list.className = 'audit-event-items';
  events.forEach((event, index) => {
    const row = document.createElement('button'); row.type = 'button';
    row.className = 'audit-event' + (index === 0 ? ' selected' : '');
    row.setAttribute('aria-pressed', index === 0 ? 'true' : 'false');
    const title = document.createElement('strong'); title.textContent = (event.event_type || 'Audit event').replaceAll('_', ' ');
    const meta = document.createElement('span'); meta.className = 'audit-meta';
    meta.textContent = (event.user_name || event.user_id || 'Unknown user') + ' · ' + (event.timestamp || 'Time unknown');
    const request = document.createElement('small'); request.textContent = (event.decision || 'Decision unavailable') + ' · ' + (event.request_id || 'No request ID');
    row.append(title, meta, request);
    row.addEventListener('click', () => {
      for (const button of list.querySelectorAll('.audit-event')) {
        const selected = button === row;
        button.classList.toggle('selected', selected);
        button.setAttribute('aria-pressed', String(selected));
      }
      renderAuditDetail(event, data.integrity);
    });
    list.appendChild(row);
  });
  els.auditResults.appendChild(list);
  if (events.length) renderAuditDetail(events[0], data.integrity);
  else document.getElementById('audit-detail').textContent = 'No event details to display.';
}

function renderAuditDetail(event, integrity) {
  const panel = document.getElementById('audit-detail'); panel.replaceChildren();
  const eyebrow = document.createElement('span'); eyebrow.className = 'reader-label'; eyebrow.textContent = 'REQUEST DETAILS';
  const heading = document.createElement('h3'); heading.textContent = event.event_type?.replaceAll('_', ' ') || 'Audit event';
  const facts = document.createElement('div'); facts.className = 'audit-facts';
  for (const [label, value] of [
    ['Request ID', event.request_id], ['User', event.user_name || event.user_id],
    ['Role', event.user_role], ['Recorded at', event.timestamp],
    ['Permission version', event.permission_epoch], ['Policy version', event.policy_version],
    ['Identity mode', event.identity_mode], ['Decision', event.decision]
  ]) {
    if (value === null || value === undefined || value === '') continue;
    const key = document.createElement('span'); key.textContent = label;
    const content = document.createElement('strong'); content.textContent = String(value);
    facts.append(key, content);
  }
  panel.append(eyebrow, heading, facts);
  const answerHeading = document.createElement('h4'); answerHeading.textContent = 'Recorded answer'; panel.append(answerHeading);
  const answer = document.createElement('p');
  answer.className = event.redacted ? 'audit-redacted' : 'audit-recorded-answer';
  answer.textContent = event.redacted ? 'Details are unavailable under the current access scope.' : (event.answer || 'No answer was recorded for this event.');
  panel.append(answer);
  if (!event.redacted && Array.isArray(event.evidence) && event.evidence.length) {
    const evidenceHeading = document.createElement('h4'); evidenceHeading.textContent = 'Recorded evidence'; panel.append(evidenceHeading);
    const evidenceList = document.createElement('ul'); evidenceList.className = 'audit-evidence-list';
    for (const item of event.evidence) {
      const li = document.createElement('li');
      li.textContent = item.doc_id + ' · Version ' + item.version + ' · ' + (item.content_hash ? 'SHA-256 ' + item.content_hash.slice(0, 12) + '…' : 'Fingerprint unavailable');
      evidenceList.appendChild(li);
    }
    panel.append(evidenceList);
  }
  if (!event.redacted && event.radar_presentation) {
    const summary = document.createElement('p'); summary.className = 'audit-radar-summary';
    summary.textContent = (event.radar_presentation.status === 'confirmed' ? 'Confirmed' : 'Pending confirmation') + ' · ' + event.radar_presentation.headline;
    panel.append(summary);
  }
  const integrityNote = document.createElement('p'); integrityNote.className = 'audit-integrity-note';
  integrityNote.textContent = integrity?.valid === true ? 'Local audit chain integrity check passed.' : 'Audit integrity check requires review.';
  panel.append(integrityNote);
}

async function runAudit(generateAnswer) {
  if (auditBusy || !currentUser || !['admin', 'compliance'].includes(currentUser.role)) return;
  const q = document.getElementById('audit-q').value.trim();
  if (generateAnswer && !q) {
    els.auditResults.textContent = 'Enter an audit question before requesting an explanation.';
    return;
  }
  const filters = {q};
  const userId = document.getElementById('audit-user').value.trim();
  const requestId = document.getElementById('audit-req').value.trim();
  if (userId) filters.user_id = userId;
  if (requestId) filters.request_id = requestId;
  const generation = requestGeneration;
  auditBusy = true;
  auditData = null;
  setAuditControls();
  els.auditAnswer.replaceChildren();
  els.auditAnswer.classList.add('hidden');
  els.auditResults.textContent = generateAnswer ? 'Checking redacted events and preparing an explanation…' : 'Searching redacted audit events…';
  try {
    const data = generateAnswer
      ? await api('/api/audit/ask', {method: 'POST', body: JSON.stringify(filters)})
      : await api(`/api/audit?${new URLSearchParams(filters)}`);
    if (generation !== requestGeneration) return;
    auditData = data;
    renderAudit(data);
    if (data.answer) {
      const heading = document.createElement('strong');
      heading.textContent = data.provider?.startsWith('openai_compatible/')
        ? 'Model explanation'
        : generateAnswer && data.events?.length ? 'Filtered selection · no reliable model answer'
          : generateAnswer ? 'Filtered selection · no matching events' : 'Filtered selection';
      const answer = document.createElement('span');
      answer.textContent = data.answer;
      els.auditAnswer.append(heading, answer);
      els.auditAnswer.classList.remove('hidden');
    }
  } catch (error) {
    if (generation === requestGeneration) {
      els.auditResults.textContent = 'Audit request failed: ' + error.message;
    }
  } finally {
    auditBusy = false;
    setAuditControls();
  }
}

async function mutate(fields) {
  try {
    await api('/api/admin/permissions', {
      method: 'POST',
      body: JSON.stringify(fields)
    });
    clearEvidence();
    await sessionStatus();
    await loadCorpora();
    await loadAdmin();
    els.adminFeedback.className = 'feedback-msg is-success';
    els.adminFeedback.textContent = 'Saved. The next request uses the updated permissions.';

    setTimeout(() => { els.adminFeedback.textContent = ''; }, 3000);
  } catch (e) {
    els.adminFeedback.className = 'feedback-msg is-error';
    els.adminFeedback.textContent = 'Error: ' + e.message;
  }
}

// Initialization and Event Listeners
document.addEventListener('DOMContentLoaded', async () => {
  // Navigation
  els.navTabs.forEach(tab => {
    tab.addEventListener('click', (e) => {
      if (e.currentTarget.classList.contains('hidden')) return;
      const view = e.currentTarget.dataset.view;
      els.navTabs.forEach(t => {
        const active = t === e.currentTarget;
        t.classList.toggle('active', active);
        if (active) t.setAttribute('aria-current', 'page');
        else t.removeAttribute('aria-current');
      });
      els.views.forEach(v => {
        const active = v.id === `view-${view}`;
        v.classList.toggle('active', active);
        v.classList.toggle('hidden', !active);
      });
      document.getElementById('current-view-label').textContent = view === 'admin' ? 'Manage Permissions' : view === 'audit' ? 'Audit Trail' : 'Workspace';
      if (view === 'admin') loadAdmin();
    });
  });

  // Buttons
  els.btnAsk?.addEventListener('click', () => query(true));
  els.btnSearch?.addEventListener('click', () => query(false));
  const closePassport = () => { if (els.docReader.open) els.docReader.close(); };
  els.btnCloseDoc?.addEventListener('click', closePassport);
  els.btnCloseDocSecondary?.addEventListener('click', closePassport);
  els.docReader?.addEventListener('click', event => { if (event.target === els.docReader) closePassport(); });
  document.getElementById('btn-edit-query')?.addEventListener('click', () => clearEvidence());
  document.querySelectorAll('[data-demo-question]').forEach(button => {
    button.addEventListener('click', () => {
      els.queryInput.value = button.dataset.demoQuestion || '';
      els.queryInput.focus();
      if (els.datasetSelect.value) query(true);
    });
  });
  els.datasetSelect?.addEventListener('change', clearEvidence);
  for (const radio of els.modeRadios) radio.addEventListener('change', clearEvidence);
  els.planningToggle?.addEventListener('change', clearEvidence);
  els.queryInput?.addEventListener('input', clearEvidence);

  // Logout
  els.logoutBtn?.addEventListener('click', async () => {
    try {
      await api('/api/logout', { method: 'POST', body: JSON.stringify({}) });
      clearEvidence();
      await sessionStatus();
      loadCorpora();
    } catch(e) { console.error('Logout failed', e); }
  });

  // Demo account switching
  els.demoSelect?.addEventListener('change', (e) => {
    if (e.target.value) selectDemoAccount(e.target.value);
  });

  // Admin forms
  els.adminForm?.addEventListener('submit', (e) => {
    e.preventDefault();
    const action = document.getElementById('admin-action').value;
    const userId = document.getElementById('admin-user-id').value;
    let payload;
    try {
      if (!userId) throw new Error('Choose an account.');
      if (action === 'binding') {
        const [corpus, principalId] = JSON.parse(document.getElementById('admin-principal').value || '[]');
        const source = adminPrincipals.find(item => item.corpus === corpus && item.principal_id === principalId);
        if (!source) throw new Error('Choose a source identity.');
        payload = {corpus: source.corpus, principal_id: source.principal_id,
                   enabled: document.getElementById('admin-binding-enabled').value === 'true'};
      } else if (action === 'restriction') {
        const corpus = document.getElementById('admin-corpus').value;
        const value = document.getElementById('admin-rule-value').value.trim();
        if (!corpus || !value) throw new Error('Choose a dataset and enter a restriction value.');
        payload = {corpus, kind: document.getElementById('admin-rule-kind').value, value,
                   denied: document.getElementById('admin-rule-denied').value === 'true'};
      } else {
        payload = {role: document.getElementById('admin-role').value,
                   clearance: Number(document.getElementById('admin-clearance').value),
                   enabled: document.getElementById('admin-enabled').value === 'true'};
      }
    } catch (err) {
      els.adminFeedback.className = 'feedback-msg is-error';
      els.adminFeedback.textContent = err.message;
      return;
    }

    mutate({ action, user_id: userId, ...payload });
  });

  els.btnLoadUsers?.addEventListener('click', loadAdmin);
  document.getElementById('admin-action')?.addEventListener('change', updateAdminAction);
  document.getElementById('admin-user-id')?.addEventListener('change', syncAdminSelected);
  document.getElementById('security-run-query')?.addEventListener('click', queryAsSelectedEmployee);

  // Audit forms
  els.auditForm?.addEventListener('submit', (e) => { e.preventDefault(); runAudit(false); });
  els.auditAsk?.addEventListener('click', () => runAudit(true));
  els.auditExport?.addEventListener('click', () => {
    if (!auditData) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(auditData, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'contextledger-audit-redacted.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  });

  // Startup sequence
  await sessionStatus();
  const accounts = await loadDemoAccounts();
  if (!currentUser && isDemoMode && document.body.dataset.demoAutoEntry === 'true' && currentCsrf) {
    const employee = accounts.find(account => account.enabled && account.role === 'member' && account.initial_source);
    if (employee) {
      await selectDemoAccount(employee.id);
      if (currentUser) els.queryInput.value = 'HarborLedger 是做什么的？';
    }
  }
  await loadCorpora();

  // Polling
  setInterval(() => { if (document.visibilityState === 'visible') sessionStatus(); }, 5000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') sessionStatus();
    else clearEvidence();
  });
});
