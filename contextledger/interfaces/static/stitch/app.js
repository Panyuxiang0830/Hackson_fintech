'use strict';
// The supplied page DOM is retained. This adapter fills its marked data slots.
const pages = Object.fromEntries([...document.querySelectorAll('main[data-page]')].map(node => [node.dataset.page,node]));
const state = {user:null,csrf:null,demo:false,accounts:[],corpora:[],question:'',corpus:'',result:null,doc:null,audit:null,people:[],principals:[],baseline:null,selectedUser:null,contentScopes:[],controlCorpus:'',generation:0,docGeneration:0,busy:false,changingIdentity:false,timelineExpanded:{radar:false,passport:false},passportOpener:null};
const one = (page,name) => pages[page]?.querySelector(`[data-slot="${name}"]`);
const all = (page,name) => [...(pages[page]?.querySelectorAll(`[data-slot="${name}"]`) || [])];
const put = (page,name,value) => all(page,name).forEach(node=>{node.textContent=String(value ?? '—');});
function placeNotice() {
  const node=document.getElementById('stitch-notice');
  for(const page of Object.keys(pages))if(one(page,'notice-host'))one(page,'notice-host').hidden=true;
  const host=one(document.body.dataset.activePage||'home','notice-host');
  if(host){host.append(node);host.hidden=node.hidden;}
}
function notice(message,tone='info') {
  const node=document.getElementById('stitch-notice');node.textContent=message||'';node.hidden=!message;node.dataset.tone=tone;
  node.setAttribute('role',tone==='error'?'alert':'status');placeNotice();
}
const element = (tag,classes,text) => {const node=document.createElement(tag);node.className=classes||'';if(text!==undefined)node.textContent=String(text);return node;};
const permitted = page => page==='security'?state.user?.role==='admin':page==='audit'?['admin','compliance'].includes(state.user?.role):true;
// Display aliases affect demo chrome only; source quotations and exports keep original data.
function displayName(value,id) {
  const name=String(value||'').replace(/（演示员工）/g,'').trim().replace('ContextLedger 管理员','ContextLedger Administrator');
  return /\p{Script=Han}/u.test(name)?`Account ${shortId(id)}`:name||shortId(id);
}
function projectLabel(value){return state.contentScopes.flatMap(c=>c.project_catalog||[]).find(p=>p.id===value)?.name||String(value).split(':').at(-1).replaceAll('-',' ');}
state.planningChoice=null;
try{const saved=localStorage.getItem('contextledger.stitch.planning');if(saved==='on'||saved==='off')state.planningChoice=saved==='on';}catch(error){/* Storage is optional. */}
function renderPlanning() {
  state.planning=Boolean(state.planningConfigured&&state.planningChoice);
  const toggle=one('home','planning-toggle');toggle.checked=state.planning;toggle.disabled=!state.planningConfigured||state.busy||state.changingIdentity;
  toggle.closest('label').title=state.planningConfigured?'Plan retrieval before searching. Turning this off searches the original question.':'Query planning is unavailable on this server.';
  put('home','planning-label',state.planningConfigured?(state.planning?'On':'Off'):'Unavailable');
}
let fitFrame=0;
function fitActions() {
  cancelAnimationFrame(fitFrame);fitFrame=requestAnimationFrame(()=>{
    for(const button of document.querySelectorAll('.stitch-fit-action')){
      if(!button.getClientRects().length)continue;
      const label=button.querySelector('.stitch-action-label');
      for(const cls of [...label.classList])if(cls.startsWith('stitch-font-'))label.classList.remove(cls);
      const base=parseFloat(getComputedStyle(label).fontSize);
      const available=label.getBoundingClientRect().width;
      for(let size=Math.floor(base);size>=10&&label.scrollWidth>available+1;size--)label.className=label.className.replace(/\bstitch-font-\d+\b/g,'')+` stitch-font-${size}`;
    }
  });
}
const actionObserver=new ResizeObserver(fitActions);
for(const button of document.querySelectorAll('.stitch-fit-action'))actionObserver.observe(button);
new MutationObserver(fitActions).observe(pages.home.parentElement,{subtree:true,childList:true,characterData:true});
document.fonts.ready.then(fitActions);window.addEventListener('resize',fitActions);

function shortId(value) {
  const chars=Array.from(String(value??'—'));
  return chars.length>22?chars.slice(0,8).join('')+'…'+chars.slice(-6).join(''):chars.join('');
}
function formattedTime(value) {
  const raw=String(value||'Time unknown');
  if(!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(raw))return {raw,time:raw,date:'',zone:''};
  const date=new Date(raw);if(!Number.isFinite(date.getTime()))return {raw,time:raw,date:'',zone:''};
  const time=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Singapore',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(date);
  return {raw,time:time+'.'+String(date.getMilliseconds()).padStart(3,'0'),date:new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Singapore',day:'2-digit',month:'short',year:'numeric'}).format(date),zone:'SGT (UTC+08:00)'};
}
function copyControl(value,label) {
  const button=element('button','stitch-copy-control');button.type='button';button.title=label;button.setAttribute('aria-label',label);
  button.append(element('span','material-symbols-outlined','content_copy'));button.disabled=!value;
  button.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(String(value));notice('Copied full identifier.');}catch(error){notice('Copy is unavailable. The complete value is included in the exported JSON.','error');}});
  return button;
}
function queryBusy(active) {
  state.busy=active;const button=pages.home.querySelector('[data-action="ask"]');button.disabled=active;button.setAttribute('aria-busy',String(active));
  put('home','ask-label',active?'Preparing answer…':'Ask ContextLedger');put('home','ask-icon',active?'progress_activity':'arrow_forward');
  one('home','ask-icon').classList.toggle('stitch-spin',active);
  one('home','question').disabled=active;one('home','corpus').disabled=active;
  for(const example of pages.home.querySelectorAll('[data-action="example"]'))example.disabled=active;
  renderPlanning();fitActions();
}
function passportLayout(focus=false) {
  const drawer=one('passport','passport-panel');const modal=document.body.dataset.activePage==='passport'&&matchMedia('(max-width:1023px)').matches;
  document.body.classList.toggle('passport-sheet-open',modal);
  drawer.setAttribute('role',modal?'dialog':'region');if(modal)drawer.setAttribute('aria-modal','true');else drawer.removeAttribute('aria-modal');
  document.querySelector('header').inert=modal;document.querySelector('aside').inert=modal;
  for(const node of pages.passport.querySelectorAll('a,button,input,select'))node.inert=modal&&!drawer.contains(node);
  if(modal&&focus)drawer.querySelector('[data-action="back-radar"]').focus({preventScroll:true});
}
function closePassport() {
  const opener=state.passportOpener;state.doc=null;state.docGeneration++;put('passport','quote','');show(state.result?'radar':'home');notice('');
  if(opener?.isConnected&&!opener.closest('[hidden]'))opener.focus();
  else (state.result?pages.radar.querySelector('[data-action="edit"]'):one('home','question')).focus();
  state.passportOpener=null;
}
function sourceURL(doc){
  try{const url=new URL(doc?.source_url);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch(error){return null;}
}
function technical(open) {
  const panel=one('passport','technical');panel.hidden=!open;
  const button=pages.passport.querySelector('[data-action="technical"]');button.setAttribute('aria-expanded',String(open));
  pages.passport.querySelector('[data-original-id="detail-arrow"]')?.classList.toggle('stitch-rotated',open);
}

async function api(url,body,isCurrent=()=>true) {
  const requestGeneration=state.generation;
  let response;
  try {response=await fetch(url,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':state.csrf||''},body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store'});}
  catch(error){throw new Error('The service could not be reached.');}
  if(!response.ok){
    const error=new Error(({400:'Check the question and selected dataset.',401:'Choose an identity to continue.',403:'This action is not available for the current identity.',404:'This source is unavailable under current access.',409:'Access or source versions changed. Please query again.',503:'The service is temporarily unavailable.'})[response.status]||'The request could not be completed.');
    error.status=response.status;
    error.stale=requestGeneration!==state.generation||!isCurrent();
    error.accessChanged=!error.stale&&[401,403,409].includes(response.status);
    if(error.accessChanged)clearProtected();
    throw error;
  }
  return response.json();
}

const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
let pageMotions=[];
let keyboardInput=false;
document.addEventListener('pointerdown',()=>{keyboardInput=false;document.documentElement.dataset.input='pointer';},true);
document.addEventListener('keydown',()=>{keyboardInput=true;document.documentElement.dataset.input='keyboard';},true);
function cancelPageMotion(){for(const animation of pageMotions)animation.cancel();pageMotions=[];}
function animatePage(page,previous){
  cancelPageMotion();
  if(!previous||page===previous||keyboardInput)return;
  const reduced=motionPreference.matches;
  const target=page==='passport'?one('passport','passport-panel'):pages[page].firstElementChild;
  const transform=page==='passport'?'translateX(24px)':previous==='passport'?'translateX(-12px)':'translateY(10px)';
  const easing=getComputedStyle(document.documentElement).getPropertyValue(page==='passport'?'--ease-drawer':'--ease-out').trim();
  pageMotions.push(target.animate(reduced?[{opacity:.85},{opacity:1}]:[{opacity:0,transform},{opacity:1,transform:'translate(0,0)'}],{duration:reduced?100:page==='passport'?250:200,easing}));
}
motionPreference.addEventListener('change',cancelPageMotion);
function show(page,{motion=true}={}) {
  const previous=document.body.dataset.activePage;
  if(!pages[page]||!permitted(page)){notice('Choose an authorised administrator or compliance identity for this page.');page='home';}
  for(const [name,node] of Object.entries(pages))node.hidden=name!==page;
  for(const link of document.querySelectorAll('[data-nav]')){
    const selected=link.dataset.nav===page||page==='radar'&&link.dataset.nav==='home'||page==='passport'&&link.dataset.nav==='home';
    link.classList.toggle('bg-text-primary',selected);link.classList.toggle('text-on-primary',selected);link.classList.toggle('font-semibold',selected);link.setAttribute('aria-current',selected?'page':'false');
  }
  document.body.dataset.activePage=page;
  document.querySelector('[data-slot="breadcrumb"]').textContent=page==='security'?'Manage Permissions':page==='audit'?'Audit Trail':'Workspace';
  passportLayout(page==='passport');placeNotice();
  window.scrollTo({top:0,behavior:'instant'});
  if(motion)animatePage(page,previous);else cancelPageMotion();
  if(page==='radar'){
    const title=one('radar','headline');title.tabIndex=-1;title.focus({preventScroll:true});
  }
  if(page==='passport'&&!document.body.classList.contains('passport-sheet-open')){
    const panel=one('passport','passport-panel');panel.focus({preventScroll:true});panel.scrollIntoView({block:'start',behavior:'instant'});
  }
}

function clearProtected() {
  state.generation++;
  state.docGeneration++;
  state.result=null;state.doc=null;state.audit=null;
  state.timelineExpanded={radar:false,passport:false};state.passportOpener=null;notice('');
  for(const page of ['radar','passport']){
    put(page,'headline','Submit a question to see the current judgment.');put(page,'explanation','');put(page,'query','Current query');
    put(page,'answer','');one(page,'answer-details').hidden=true;one(page,'answer-details').open=false;
    put(page,'verdict','Waiting for query');put(page,'timeline-note','');one(page,'timeline')?.replaceChildren();one(page,'evidence-list')?.replaceChildren();
    put(page,'event-count','0 source events');put(page,'evidence-caption','Current request evidence');
    if(one(page,'timeline-toggle'))one(page,'timeline-toggle').hidden=true;
    if(one(page,'needs'))one(page,'needs').hidden=true;
  }
  for(const name of ['claim','claim-scope','citation-source','quote','doc-version','doc-time','doc-indexed','doc-access','technical','doc-access-status','doc-source-status','doc-policy'])put('passport',name,'—');
  technical(false);
  for(const name of ['events','audit-facts','audit-evidence','audit-authorisations'])one('audit',name)?.replaceChildren();
  put('audit','audit-question','No event selected.');pages.passport.querySelector('[data-action="original"]').hidden=true;
  put('audit','audit-answer','Select an event to view its released details.');put('audit','audit-id','Request details');put('audit','events-count','0 found');put('audit','audit-evidence-count','0 items');put('audit','integrity','Audit chain not checked');
  show('home',{motion:false});
}

async function refreshSession() {
  const requestGeneration=state.generation;
  const data=await api('/api/session');
  if(requestGeneration!==state.generation)return null;
  const previous=state.user;
  if(previous && (previous.id!==data.user?.id || previous.epoch!==data.user?.epoch))clearProtected();
  state.user=data.user;state.csrf=data.csrf;state.demo=Boolean(data.demo_mode);
  state.demoAutoEntry=Boolean(data.demo_mode&&data.demo_auto_entry);
  state.planningConfigured=Boolean(data.workflows?.planner_configured);
  if(state.planningChoice===null)state.planningChoice=Boolean(data.workflows?.planner_enabled);
  renderPlanning();
  put('radar','epoch',state.user?.epoch??'—');
  put('radar','employee',state.user?displayName(state.user.name,state.user.id):'No identity');
  for(const link of document.querySelectorAll('[data-role-required]'))link.hidden=link.dataset.roleRequired==='admin'?state.user?.role!=='admin':!['admin','compliance'].includes(state.user?.role);
  if(!permitted(document.body.dataset.activePage))show('home');
  if(!state.user||state.user.role!=='admin'){
    state.people=[];state.principals=[];state.baseline=null;state.selectedUser=null;state.contentScopes=[];state.controlCorpus='';
    one('security','source-controls').replaceChildren();one('security','project-controls').replaceChildren();one('security','attribute-controls').hidden=true;one('security','document-rules').replaceChildren();one('security','content-corpus').replaceChildren();
    for(const name of ['employee-select','binding-select','before-bindings','after-bindings'])one('security',name)?.replaceChildren();
    put('security','before-count','—');put('security','after-count','—');put('security','permission-feedback','Administrator access required.');
  }
  return data;
}

async function loadAccounts() {
  const selector=document.querySelector('[data-slot="identity-select"]');
  selector.replaceChildren();
  if(!state.demo){const option=element('option','',state.user?`${displayName(state.user.name,state.user.id)} · ${state.user.role}`:'No signed-in identity');selector.append(option);selector.disabled=true;return;}
  state.accounts=await api('/api/demo/accounts');
  const placeholder=element('option','','Choose demo identity');placeholder.value='';selector.append(placeholder);
  for(const account of state.accounts){const option=element('option','',`${displayName(account.name,account.id)} · ${account.role}`);option.value=account.id;option.disabled=!account.enabled;selector.append(option);}
  selector.value=state.user?.id||'';
}

async function loadCorpora() {
  const selector=one('home','corpus');selector.replaceChildren();
  const placeholder=element('option','','Select a dataset');placeholder.value='';selector.append(placeholder);
  state.corpora=state.user?await api('/api/corpora'):[];
  for(const corpus of state.corpora){const option=element('option','',corpus.label);option.value=corpus.id;selector.append(option);}
  if(state.corpora.some(item=>item.id===state.corpus))selector.value=state.corpus;
  else if(state.corpora.some(item=>item.id==='orgforge'))selector.value='orgforge';
  else if(state.corpora.length===1)selector.value=state.corpora[0].id;
  state.corpus=selector.value;
}

async function switchIdentity(userId) {
  if(state.changingIdentity||!userId)return;
  state.changingIdentity=true;clearProtected();notice('Switching demo identity…');
  const selector=document.querySelector('[data-slot="identity-select"]');selector.disabled=true;
  try {await api('/api/demo/select',{user_id:userId});await refreshSession();await loadAccounts();await loadCorpora();notice('');}
  finally {state.changingIdentity=false;selector.disabled=!state.demo;renderPlanning();}
}

function renderTimeline(page,data) {
  const list=one(page,'timeline');if(!list)return;list.replaceChildren();
  const evidence=data.evidence||[];
  const events=data.radar?.event_candidates||[];
  put(page,'timeline-note',events.length?'Ordered by source record time within comparable groups. A Slack record time does not verify the time of a GitHub operation. '+(data.radar?.timeline_order?.groups?.length>1?'Different time bases and unknown times are grouped separately; there is no single verified chronology.':''): '');
  put(page,'event-count',`${events.length} source event${events.length===1?'':'s'}`);
  const toggle=one(page,'timeline-toggle');toggle.hidden=events.length<=4;toggle.setAttribute('aria-expanded',String(state.timelineExpanded[page]));
  toggle.setAttribute('aria-controls',list.id||(list.id='stitch-'+page+'-events'));
  toggle.textContent=state.timelineExpanded[page]?'Show fewer':`Show all ${events.length}`;
  if(!events.length){list.append(element('p','font-body-sm text-body-sm text-text-muted','This request did not return a source timeline.'));return;}
  for(const [index,event] of events.entries()){
    const template=document.querySelector('template[data-template="timeline"]');
    const node=template.content.firstElementChild.cloneNode(true);
    const hit=evidence.find(item=>item.citation_id===event.citation_id);
    const sourceTime=event.source_record_time??event.event_time;
    const time=formattedTime(sourceTime);const meta=node.querySelector('[data-slot="event-meta"]');
    const zone=event.time_group==='local_timestamp'?' · Timezone unspecified':time.zone?' SGT':'';
    meta.textContent=`Source record time: ${time.date?time.date+' · ':''}${time.time}${zone}${event.time_precision==='day'?' · Day precision':''} · ${hit?.source||event.type||'Source record'}${event.historical?' · Historical revision':''}`;meta.title=`${event.time_basis||'Source time'}: ${time.raw}`;
    const title=node.querySelector('[data-slot="event-title"]');title.classList.add('stitch-event-title');title.replaceChildren();
    const name=element('span','stitch-event-name',hit?.title||'Source record');name.title=name.textContent;
    const citation=element('button','stitch-citation text-primary font-bold',`[${event.citation_id}]`);citation.type='button';citation.setAttribute('aria-label',`Open source ${event.citation_id}`);citation.addEventListener('click',()=>openPassport(hit));title.append(name,citation);
    const quote=node.querySelector('[data-slot="event-quote"]');quote.textContent=event.quote||'';quote.title=quote.textContent;quote.classList.add('stitch-event-quote');
    for(const warning of event.time_warnings||[]){
      if(warning.startsWith('Timezone unspecified;'))continue; // Already beside the time.
      const note=element('p','font-body-sm text-body-sm text-text-muted',warning);note.dataset.timeWarning='true';quote.after(note);
    }
    node.hidden=index>=4&&!state.timelineExpanded[page];list.append(node);
  }
}

function renderJudgment(page,data) {
  const p=data.radar_presentation;
  put(page,'query',state.question);
  put(page,'headline',p?.headline||(data.decision==='insufficient'?'Evidence is insufficient to confirm this question.':'Answer from the current authorised selection'));
  put(page,'explanation',p?.explanation||data.answer||'No reliable answer was generated.');
  const details=one(page,'answer-details');
  details.hidden=!p?.explanation||!data.answer||p.explanation.trim()===data.answer.trim();details.open=false;
  put(page,'answer',details.hidden?'':data.answer);
  if(one(page,'verdict')){
    const label=p?.status==='confirmed'?'Confirmed':p?.status==='pending_confirmation'?'Pending confirmation':data.provider==='mock_fallback'?'Model answer unavailable':data.decision==='insufficient'?'Insufficient evidence':'Source-based answer';
    put(page,'verdict',label);
    const warning=p?.status==='pending_confirmation'||data.provider==='mock_fallback'||data.decision==='insufficient';
    const badge=one(page,'verdict');badge.classList.toggle('bg-status-warning-bg',warning);badge.classList.toggle('text-status-warning',warning);badge.classList.toggle('bg-mint-badge-bg',p?.status==='confirmed');badge.classList.toggle('text-status-success',p?.status==='confirmed');badge.classList.toggle('bg-canvas-bg',!p&&!warning);badge.classList.toggle('text-text-muted',!p&&!warning);
  }
  const needs=one(page,'needs');if(needs){needs.hidden=p?.status!=='pending_confirmation';
    put(page,'pending-label',data.radar?.disagreements?.length?'Source differences require review':'Pending evidence checks');
    const content=one(page,'needs-content');content.replaceChildren();
    for(const item of p?.needs_confirmation||[]){const line=element('span','block',item.item);for(const id of item.citation_ids||[]){const hit=(data.evidence||[]).find(hit=>hit.citation_id===id);const button=element('button','stitch-citation text-primary font-bold',`[${id}]`);button.type='button';button.setAttribute('aria-label',`Open source ${id}`);button.addEventListener('click',()=>openPassport(hit));line.append(button);}content.append(line);}
  }
  renderTimeline(page,data);
}

function renderResult(data) {
  state.result=data;renderJudgment('radar',data);
  const evidence=data.evidence||[];const list=one('radar','evidence-list');list.replaceChildren();
  put('radar','evidence-caption',`${evidence.length} authorised records in this request`);
  const coverage=data.radar?.coverage;
  put('radar','coverage',coverage?`${coverage.documents} authorised records examined${coverage.truncation_reasons?.length?' · Bounded selection':''}. Event times marked unknown remain unknown.`:'Current authorised evidence selection.');
  for(const hit of evidence){
    const button=element('button','stitch-evidence-card flex items-center gap-3 p-3 rounded-xl bg-canvas-bg hover:bg-secondary-container transition-all text-left');button.type='button';button.title=hit.title||'Source record';
    button.append(element('span','w-7 h-7 flex-shrink-0 rounded-lg bg-surface-card flex items-center justify-center font-label-sm text-label-sm font-bold',hit.citation_id));
    button.append(element('span','stitch-evidence-title font-body-md text-body-md text-text-primary font-semibold flex-1',`[${hit.citation_id}] ${hit.title||'Source record'}`));button.append(element('span','material-symbols-outlined text-text-muted text-[18px]','chevron_right'));
    button.addEventListener('click',()=>openPassport(hit));list.append(button);
  }
  if(!evidence.length)list.append(element('p','font-body-sm text-body-sm text-text-muted','No authorised evidence was returned.'));
  show('radar');
}

async function ask() {
  if(state.busy||state.changingIdentity)return;
  const question=one('home','question').value.trim(),corpus=one('home','corpus').value;
  if(!state.user||!question||!corpus){notice('Choose an identity and dataset, then enter a question.','error');return;}
  clearProtected();state.question=question;state.corpus=corpus;queryBusy(true);const generation=state.generation;
  try {const data=await api('/api/ask',{q:question,corpus,mode:'hybrid',planning:state.planning,output_language:'en'});if(generation===state.generation){renderResult(data);notice(data.provider==='mock_fallback'?'No reliable model answer was generated. The authorised selection remains available.':'','error');}}
  catch(error){if(generation===state.generation||error.accessChanged)notice(error.message,'error');}
  finally {queryBusy(false);}
}

async function openPassport(hit) {
  if(!hit||!state.result)return;
  state.passportOpener=document.activeElement;state.timelineExpanded.passport=false;
  const generation=state.generation,docRequest=++state.docGeneration;state.doc=null;
  for(const name of ['claim-scope','citation-source','quote','doc-version','doc-time','doc-indexed','doc-access','technical','doc-source-status','doc-policy'])put('passport',name,'—');
  technical(false);
  pages.passport.querySelector('[data-action="original"]').hidden=true;
  renderJudgment('passport',state.result);put('passport','claim','Loading source…');put('passport','doc-access-status','Checking access');show('passport');notice('Checking current source access…');
  try {
    const data=await api('/api/doc?'+new URLSearchParams({corpus:hit.corpus||state.corpus,doc_id:hit.doc_id}),undefined,()=>docRequest===state.docGeneration&&document.body.dataset.activePage==='passport');
    if(generation!==state.generation||docRequest!==state.docGeneration||document.body.dataset.activePage!=='passport')return;
    if(!data.available||!data.doc){clearProtected();const error=new Error('This source is unavailable under current access.');error.accessChanged=true;throw error;}
    state.doc=data.doc;
    pages.passport.querySelector('[data-action="original"]').hidden=!sourceURL(state.doc);
    put('passport','doc-access-status','Authorised source');put('passport','doc-source-status',data.doc.source_check||'Unknown');
    put('passport','claim-scope','This passport shows the selected source and its current access metadata.');
    put('passport','claim',data.doc.title||hit.title||'Cited source');
    put('passport','citation-source',`[${hit.citation_id}] ${data.doc.source||hit.source||'Source'} · Original text`);
    put('passport','quote',data.doc.text||'No source text was returned.');put('passport','doc-version',data.doc.version);put('passport','doc-time',data.doc.ts||'Unknown');put('passport','doc-indexed',data.doc.indexed_at||'Unknown');put('passport','doc-access',data.doc.acl_basis||'Current session access');
    const metadata=data.doc.metadata||{};
    put('passport','doc-policy',metadata.project?`${metadata.project_name||projectLabel(metadata.project)} · ${metadata.classification||'Internal'}`:'');
    put('passport','technical',JSON.stringify({request_id:state.result.request_id,document_id:hit.doc_id,version:data.doc.version,content_hash:data.doc.content_hash||null,source_check:data.doc.source_check||'Unknown',freshness:data.doc.freshness||'Unknown',current_acl_basis:data.doc.acl_basis||null,acl_provenance:metadata.acl_provenance||null,current_source_acl_basis:metadata.source_acl_basis||null,current_source_acl_observed_at:metadata.source_acl_observed_at||null,unverified_source_acl_reference:metadata.source_acl_reference||null,source_revision:metadata.source_revision||null},null,2));
    notice('');
  } catch(error){if(docRequest!==state.docGeneration&&!error.accessChanged)return;if(error.status===404){clearProtected();notice(error.message,'error');}else if(generation===state.generation){put('passport','claim','Source unavailable');put('passport','quote','The source cannot be opened under the current access scope.');put('passport','doc-access-status','Unavailable');state.doc=null;notice(error.message,'error');}else if(error.accessChanged)notice(error.message,'error');}
}

async function loadSecurity() {
  if(state.user?.role!=='admin')return;
  const generation=state.generation;
  const people=await api('/api/admin/users');if(generation!==state.generation)return;
  state.people=people;
  const selector=one('security','employee-select');const prior=state.selectedUser;selector.replaceChildren();
  for(const person of people.filter(p=>p.role==='member')){const option=element('option','',`${displayName(person.name,person.id)} · ${displayName(person.department||person.role,person.id)}`);option.value=person.id;option.disabled=!person.enabled;selector.append(option);}
  selector.value=people.some(p=>p.id===prior&&p.role==='member')?prior:(people.find(p=>p.enabled&&p.role==='member')?.id||'');
  await selectEmployee(selector.value);
}

async function selectEmployee(userId) {
  const person=state.people.find(p=>p.id===userId);if(!person)return;
  if(state.selectedUser!==userId||!state.baseline)state.baseline=structuredClone(person);
  state.selectedUser=userId;const generation=state.generation;
  setPermissionBusy(true);
  try {
    const catalog=await api('/api/admin/content-scopes?'+new URLSearchParams({user_id:userId}));
    if(generation!==state.generation||state.selectedUser!==userId)return;
    state.contentScopes=catalog;
    const selector=one('security','content-corpus');selector.replaceChildren();
    for(const item of catalog){const option=element('option','',item.id);option.value=item.id;selector.append(option);}
    selector.value=catalog.some(item=>item.id===state.controlCorpus)?state.controlCorpus:catalog.some(item=>item.id==='orgforge')?'orgforge':catalog[0]?.id||'';
    state.controlCorpus=selector.value;renderContentAccess();
  } finally {setPermissionBusy(false);}
}

function contentState(person) {
  const corpus=state.controlCorpus;
  const rules=(person.restrictions||[]).filter(r=>r.corpus===corpus||r.corpus==='*');
  const bound=(person.bindings||[]).some(b=>b.corpus===corpus&&b.enabled);
  const globalRule=rules.some(r=>r.corpus==='*');
  const blocked=rules.some(r=>r.kind==='corpus'&&(r.value===corpus||r.value==='*'))||rules.some(r=>['source','project','department','document'].includes(r.kind)&&r.value==='*');
  const sources=state.contentScopes.find(c=>c.id===corpus)?.sources||[];
  return {rules,bound,blocked,globalRule,sources,allowed:sources.filter(source=>bound&&!blocked&&!rules.some(r=>r.kind==='source'&&r.value===source))};
}

function setPermissionBusy(busy) {
  for(const node of pages.security.querySelectorAll('input,select,button'))node.disabled=busy;
  if(!busy&&state.selectedUser)renderContentAccess();
}

function renderContentAccess() {
  const person=state.people.find(p=>p.id===state.selectedUser);if(!person)return;
  const current=contentState(person);put('security','epoch',person.epoch);
  put('security','binding-description',`Choose which ${state.controlCorpus||'dataset'} sources ${displayName(person.name,person.id)} may read. Imported source ACLs still apply.`);
  const mapped=(person.bindings||[]).filter(b=>b.corpus===state.controlCorpus);
  const select=one('security','binding-select');select.replaceChildren();
  for(const binding of mapped){const option=element('option','',`${binding.principal_id} · ${binding.enabled?'Linked':'Disabled'}`);option.value=JSON.stringify([binding.corpus,binding.principal_id]);select.append(option);}
  const restore=pages.security.querySelector('[data-action="binding"]');restore.hidden=current.bound||!mapped.length;
  put('security','binding-label','Restore this mapped identity');select.hidden=current.bound||!mapped.length;
  const enabled=one('security','dataset-access');enabled.checked=current.bound&&!current.blocked;enabled.disabled=!current.bound||!state.controlCorpus||current.globalRule;
  const controls=one('security','source-controls');controls.replaceChildren();
  for(const source of current.sources){
    const label=element('label','stitch-access-row');const input=element('input');input.type='checkbox';input.dataset.sourcePermission=source;input.checked=current.allowed.includes(source);input.disabled=!current.bound||current.blocked||current.globalRule;
    const name=({slack:'Slack',jira:'Jira',confluence:'Confluence',google_drive:'Google Drive'})[source]||source;
    label.append(input,element('span','',name));controls.append(label);
  }
  one('security','attribute-controls').hidden=false;
  one('security','clearance-select').value=String(person.clearance);
  renderProjects(person);
  const documents=one('security','document-rules');documents.replaceChildren();
  for(const rule of current.rules.filter(r=>r.kind==='document')){
    const row=element('div','stitch-access-row');row.append(element('span','stitch-wrap',rule.value));
    const button=element('button','stitch-copy-control','Restore');button.type='button';button.dataset.restoreDocument=rule.value;button.disabled=rule.corpus==='*'||rule.value==='*';row.append(button);documents.append(row);
  }
  one('security','document-id').disabled=!state.controlCorpus||current.globalRule;
  pages.security.querySelector('[data-action="deny-document"]').disabled=!state.controlCorpus||current.globalRule;
  for(const [prefix,user] of [['before',state.baseline],['after',person]]){
    const access=contentState(user);const list=one('security',prefix+'-bindings');list.replaceChildren();put('security',prefix+'-count',access.allowed.length);
    for(const source of access.sources){const row=element('div','stitch-access-row');row.append(element('span','',source),element('span',access.allowed.includes(source)?'text-status-success':'text-text-muted',access.allowed.includes(source)?'Allowed':'Blocked'));list.append(row);}
    list.append(element('p','font-body-sm text-text-muted',`Clearance: ${['Public','Internal','Confidential','Restricted'][user.clearance]}`));
    const names=(state.contentScopes.find(c=>c.id===state.controlCorpus)?.project_catalog||[]).filter(p=>(user.projects||[]).includes(p.id)).map(p=>p.name);
    if(names.length)list.append(element('p','font-body-sm text-text-muted',`Projects: ${names.join(', ')}`));
    if(access.rules.some(r=>r.kind==='document'))list.append(element('p','font-body-sm text-text-muted',`${access.rules.filter(r=>r.kind==='document').length} document restriction(s).`));
    if(!access.bound)list.append(element('p','font-body-sm text-text-muted','Mapped source identity is disabled.'));
  }
  put('security','before-epoch',`Permission version ${state.baseline.epoch}`);
  put('security','permission-feedback',`Permission version ${state.baseline.epoch} → ${person.epoch}`);
}

function renderProjects(person) {
  const catalog=state.contentScopes.find(c=>c.id===state.controlCorpus)?.project_catalog||[];
  const selected=one('security','project-controls');selected.replaceChildren();
  for(const project of catalog.filter(p=>(person.projects||[]).includes(p.id))){
    const chip=element('div','stitch-project-chip');
    const remove=element('button','stitch-project-remove','×');remove.type='button';remove.dataset.removeProject=project.id;remove.setAttribute('aria-label',`Remove project ${project.name}`);
    chip.append(element('span','',project.name),remove);selected.append(chip);
  }
  if(!selected.children.length)selected.append(element('span','font-body-sm text-text-muted','No projects assigned'));
  const query=one('security','project-search').value.trim().toLocaleLowerCase();
  const results=one('security','project-results');results.replaceChildren();
  const available=catalog.filter(p=>!(person.projects||[]).includes(p.id)&&p.name.toLocaleLowerCase().includes(query));
  if(query)for(const project of available){const button=element('button','stitch-project-option',`+ ${project.name}`);button.type='button';button.dataset.addProject=project.id;results.append(button);}
  if(query&&!available.length)results.append(element('span','font-body-sm text-text-muted','No matching projects'));
  results.hidden=!query;
}

async function saveContentPermission(fields) {
  if(state.busy||state.user?.role!=='admin')return;state.busy=true;setPermissionBusy(true);
  try {
    const person=state.people.find(p=>p.id===state.selectedUser);
    await api('/api/admin/permissions',{user_id:person.id,corpus:state.controlCorpus,...fields});
    clearProtected();show('security');await loadSecurity();notice('Reading permissions saved. The dataset remains selectable.');
  } catch(error){notice(error.message,'error');}
  finally{state.busy=false;setPermissionBusy(false);}
}

async function changeBinding() {
  const person=state.people.find(p=>p.id===state.selectedUser);let selected;
  try{selected=JSON.parse(one('security','binding-select').value);}catch(error){return;}
  if(!person?.bindings?.some(b=>b.corpus===selected[0]&&b.principal_id===selected[1]&&!b.enabled))return;
  await saveContentPermission({action:'binding',corpus:selected[0],principal_id:selected[1],enabled:true});
}

async function runEmployeeQuery() {
  const userId=state.selectedUser;if(!userId||!state.demo)return;
  const question=state.question||pages.home.querySelector('[data-action="example"]')?.dataset.question||'What can I monitor in the ENG-195 SwiftUI telemetry health dashboard?';
  const corpus=state.controlCorpus;await switchIdentity(userId);if(state.corpora.some(c=>c.id===corpus)){state.corpus=corpus;one('home','corpus').value=corpus;}one('home','question').value=question;await ask();
}

async function loadAudit() {
  if(state.busy||!permitted('audit'))return;
  const filters={};for(const [slot,key] of [['audit-query','q'],['audit-user','user_id'],['audit-request','request_id']]){const value=one('audit',slot)?.value.trim();if(value)filters[key]=value;}
  const generation=state.generation;state.busy=true;notice('Reading audit events under current access…');
  state.audit=null;
  for(const name of ['events','audit-facts','audit-evidence','audit-authorisations'])one('audit',name)?.replaceChildren();
  put('audit','audit-question','Searching the current audit selection…');
  put('audit','audit-id','Request details');put('audit','audit-answer','Searching the current audit selection…');put('audit','integrity','Audit chain not checked');
  try {const data=await api('/api/audit?'+new URLSearchParams(filters));if(generation!==state.generation)return;
    state.audit={...data,events:(data.events||[]).map(event=>event.redacted?{...event,question:null,query:null,answer:null,evidence:[],authorization_decisions:[],retrieved_document_ids:[],radar_presentation:null}:event)};
    renderAudit(state.audit);notice('');}
  catch(error){if(generation===state.generation||error.accessChanged)notice(error.message,'error');}finally{state.busy=false;}
}

function renderAudit(data) {
  const list=one('audit','events');list.replaceChildren();const events=data.events||[];put('audit','events-count',`${events.length} found`);put('audit','integrity',data.integrity?.valid===true?'Local audit chain valid':'Audit chain requires review');
  for(const [index,event] of events.entries()){
    const button=element('button','stitch-audit-event event-card group relative p-4 rounded-xl bg-canvas-bg shadow-sm cursor-pointer transition-all text-left w-full');button.type='button';button.setAttribute('aria-pressed',String(index===0));
    const time=formattedTime(event.timestamp);const meta=element('span','font-label-sm text-label-sm text-text-muted',`${time.time}${time.zone?' SGT':''} · ${event.event_type?.replaceAll('_',' ')||'Event'}`);meta.title=time.raw;
    const title=element('h4','stitch-evidence-title font-title-md text-title-md font-bold text-text-primary',event.redacted?(event.evidence_visibility==='not_recorded'?'Event recorded without evidence':'Details withheld under current access'):event.query||event.question||event.event_type||'Audit event');
    const actor=element('span','stitch-audit-muted',`${displayName(event.user_name||event.user_id,event.user_id)} · ${shortId(event.request_id)}`);actor.title=`${displayName(event.user_name||event.user_id,event.user_id)} · ${event.request_id||''}`;
    button.append(meta,title,actor);
    button.addEventListener('click',()=>{for(const row of list.querySelectorAll('button'))row.setAttribute('aria-pressed',String(row===button));renderAuditDetails(event,data.integrity);});list.append(button);if(index===0)renderAuditDetails(event,data.integrity);
  }
  if(!events.length){list.append(element('p','font-body-sm text-body-sm text-text-muted','No events matched this filter.'));put('audit','audit-answer','No event selected.');}
}

function renderAuditDetails(event,integrity) {
  put('audit','audit-id',shortId(event.request_id));one('audit','audit-id').title=event.request_id||'Request details';const facts=one('audit','audit-facts');facts.replaceChildren();
  const card=label=>{const node=element('div','p-3.5 rounded-xl bg-canvas-bg flex flex-col gap-1');node.append(element('span','font-label-sm text-label-sm text-text-muted uppercase tracking-wider',label));facts.append(node);return node;};
  const request=card('Request / employee'),idRow=element('div','stitch-audit-id-row'),id=element('code','stitch-audit-id',shortId(event.request_id));id.title=event.request_id||'';idRow.append(id,copyControl(event.request_id,'Copy full request ID'));request.append(idRow);
  const actor=element('span','stitch-audit-muted',displayName(event.user_name||event.user_id,event.user_id));actor.title=actor.textContent;request.append(actor);
  const recorded=card('Recorded at'),time=formattedTime(event.timestamp),timeValue=element('strong','stitch-audit-time',time.time);timeValue.title=time.raw;recorded.append(timeValue);
  if(time.date)recorded.append(element('span','stitch-audit-muted',time.date));if(time.zone)recorded.append(element('span','stitch-audit-muted',time.zone));
  const policy=card('Permission / policy');policy.append(element('strong','stitch-audit-time',`Version ${event.permission_epoch??'—'}`));const name=element('span','stitch-audit-policy',event.policy_version||'Policy unavailable');name.title=name.textContent;policy.append(name);
  put('audit','audit-mask',event.redacted?'Details masked under current access':'Current evidence access checked');
  put('audit','audit-answer',event.redacted?'Recorded question, answer and evidence details are withheld under current access.':event.answer||'No answer was recorded for this event.');
  const body=one('audit','audit-evidence');body.replaceChildren();const evidence=event.redacted?[]:event.evidence||[];
  const visibility=event.evidence_visibility|| (event.redacted?'withheld':evidence.length?'visible':'not_recorded');
  put('audit','audit-evidence-count',visibility==='not_recorded'?'Not recorded':event.redacted?'Withheld':`${evidence.length} items`);
  one('audit','audit-evidence-count').dataset.visibility=visibility;
  one('audit','audit-mask').classList.toggle('stitch-audit-masked',Boolean(event.redacted));
  one('audit','audit-mask').classList.toggle('stitch-audit-released',!event.redacted);
  put('audit','audit-question',event.redacted?'Recorded text is withheld under current access.':event.query||event.question||'No question was recorded for this event.');
  for(const item of evidence){const row=element('tr','hover:bg-canvas-bg/80 transition-colors');const document=element('td','py-3.5 px-4 font-body-sm text-body-sm stitch-wrap',item.title||shortId(item.doc_id));document.title=item.doc_id||'Source record';row.append(document);for(const value of [item.version||'—','Authorised at this audit read'])row.append(element('td','py-3.5 px-4 font-body-sm text-body-sm stitch-wrap',value));body.append(row);}
  if(!evidence.length){const messages={not_recorded:'This event did not record any evidence.',current_access_unavailable:'Historical evidence details are withheld because current access could not be verified. This may also occur when a source is no longer available.',version_mismatch:'Historical evidence details are withheld because the recorded version or hash no longer matches the current source.',index_unavailable:'Historical evidence details are withheld because the current index could not be verified.'};const row=element('tr','');const cell=element('td','py-3.5 px-4 text-text-muted',messages[visibility]||'Historical evidence details are withheld under current access.');cell.colSpan=3;row.append(cell);body.append(row);}
  const authorisations=one('audit','audit-authorisations');authorisations.replaceChildren();
  for(const check of event.redacted?[]:event.authorization_decisions||[]){const line=element('p','stitch-wrap',`${shortId(check.document_id)} · ${check.allowed===true?'Allowed at request time':check.allowed===false?'Denied at request time':'Recorded outcome unknown'} · ${check.reason||'No recorded reason'}`);authorisations.append(line);}
  if(!authorisations.children.length)authorisations.append(element('p','text-text-muted',event.redacted&&visibility!=='not_recorded'?'Authorisation details are withheld with the evidence.':'No document authorisation checks were released for this event.'));
}

async function dispatch(actionName,node) {
  if(actionName==='legacy'){location.href='/';return;}
  if(actionName==='ask')return ask();
  if(actionName==='example'){one('home','question').value=node.dataset.question||'';return ask();}
  if(actionName==='edit'){show('home');one('home','question').focus();return;}
  if(actionName==='open-first')return openPassport(state.result?.evidence?.[0]);
  if(actionName==='back-radar'){closePassport();return;}
  if(actionName==='technical'){technical(one('passport','technical').hidden);return;}
  if(actionName==='toggle-timeline'){const page=node.closest('[data-page]').dataset.page;state.timelineExpanded[page]=!state.timelineExpanded[page];if(state.result)renderTimeline(page,state.result);return;}
  if(actionName==='original'){const url=sourceURL(state.doc);if(url)window.open(url,'_blank','noopener,noreferrer');return;}
  if(actionName==='binding')return changeBinding();
  if(actionName==='query-employee')return runEmployeeQuery();
  if(actionName==='audit-search')return loadAudit();
  if(actionName==='audit-export'&&state.audit){const url=URL.createObjectURL(new Blob([JSON.stringify(state.audit,null,2)],{type:'application/json'}));const a=element('a','');a.href=url;a.download='contextledger-audit-redacted.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
}

document.addEventListener('click',event=>{
  const nav=event.target.closest('[data-nav]');if(nav){event.preventDefault();notice('');show(nav.dataset.nav);if(nav.dataset.nav==='security')loadSecurity().catch(error=>notice(error.message,'error'));return;}
  const button=event.target.closest('[data-action]');if(button){event.preventDefault();Promise.resolve(dispatch(button.dataset.action,button)).catch(error=>notice(error.message,'error'));}
});
document.querySelector('[data-slot="identity-select"]').addEventListener('change',event=>switchIdentity(event.target.value).catch(error=>notice(error.message,'error')));
one('security','employee-select').addEventListener('change',event=>selectEmployee(event.target.value).catch(error=>notice(error.message,'error')));
one('security','content-corpus').addEventListener('change',event=>{state.controlCorpus=event.target.value;renderContentAccess();});
one('security','dataset-access').addEventListener('change',event=>saveContentPermission({action:'restriction',kind:'corpus',value:state.controlCorpus,denied:!event.target.checked}));
one('security','source-controls').addEventListener('change',event=>{if(event.target.dataset.sourcePermission)saveContentPermission({action:'restriction',kind:'source',value:event.target.dataset.sourcePermission,denied:!event.target.checked});});
one('security','project-search').addEventListener('input',()=>{const person=state.people.find(p=>p.id===state.selectedUser);if(person)renderProjects(person);});
one('security','project-controls').addEventListener('click',event=>{const button=event.target.closest('[data-remove-project]');if(button)saveContentPermission({action:'project_membership',project:button.dataset.removeProject,enabled:false});});
one('security','project-results').addEventListener('click',event=>{const button=event.target.closest('[data-add-project]');if(button)saveContentPermission({action:'project_membership',project:button.dataset.addProject,enabled:true});});
one('security','clearance-select').addEventListener('change',event=>saveContentPermission({action:'account',clearance:Number(event.target.value)}));
one('security','document-rules').addEventListener('click',event=>{const button=event.target.closest('[data-restore-document]');if(button)saveContentPermission({action:'restriction',kind:'document',value:button.dataset.restoreDocument,denied:false});});
pages.security.querySelector('[data-action="deny-document"]').addEventListener('click',()=>{const id=one('security','document-id').value.trim();if(id)saveContentPermission({action:'restriction',kind:'document',value:id,denied:true});else notice('Enter a document ID from Evidence Passport.','error');});
one('home','corpus').addEventListener('change',()=>{state.corpus=one('home','corpus').value;clearProtected();});
one('home','planning-toggle').addEventListener('change',event=>{state.planningChoice=event.target.checked;try{localStorage.setItem('contextledger.stitch.planning',state.planningChoice?'on':'off');}catch(error){/* Storage is optional. */}renderPlanning();});
one('audit','audit-form').addEventListener('submit',event=>{event.preventDefault();loadAudit().catch(error=>notice(error.message,'error'));});
one('home','question').addEventListener('input',()=>{if(state.result)clearProtected();else notice('');});
matchMedia('(max-width:1023px)').addEventListener('change',()=>passportLayout(document.body.dataset.activePage==='passport'));
document.addEventListener('keydown',event=>{
  if(document.body.dataset.activePage!=='passport')return;
  if(event.key==='Escape'){event.preventDefault();closePassport();return;}
  if(event.key==='Tab'&&document.body.classList.contains('passport-sheet-open')){
    const drawer=one('passport','passport-panel');const items=[...drawer.querySelectorAll('button:not(:disabled),a[href],input,select,[tabindex="0"]')].filter(node=>!node.closest('[hidden]')&&node.getClientRects().length);
    const first=items[0],last=items.at(-1);if(!first){event.preventDefault();drawer.focus();return;}
    if(event.shiftKey&&(document.activeElement===first||document.activeElement===drawer)){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }
});
document.addEventListener('visibilitychange',()=>{if(document.hidden)clearProtected();});
window.addEventListener('pagehide',clearProtected);

(async()=>{
  try {await refreshSession();await loadAccounts();
    if(!state.user&&state.demoAutoEntry){const employee=state.accounts.find(account=>account.enabled&&account.role==='member'&&account.initial_source);if(employee)await switchIdentity(employee.id);}
    await loadCorpora();show('home');notice(state.user?'':'Choose an identity to continue.');
    setInterval(()=>{if(!document.hidden&&!state.busy&&!state.changingIdentity)refreshSession().catch(error=>{clearProtected();notice(error.message,'error');});},5000);
  }catch(error){clearProtected();notice(error.message,'error');}
})();
