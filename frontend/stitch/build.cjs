/* Import the supplied HTML, retaining its DOM and utility classes. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { parseHTML } = require('linkedom');
const root = path.resolve(__dirname, '../..');
const out = path.join(root, 'contextledger/interfaces/static/stitch');
const source = path.join(__dirname, 'source');
const pages = {home:'01_search_home',radar:'02_decision_radar',passport:'03_evidence_passport',security:'04_security_lens',audit:'05_audit_trail'};
const norm = value => value.replace(/\s+/g, ' ').trim();
const leaf = (node, text) => [...node.querySelectorAll('*')].reverse().find(el => norm(el.textContent) === text);
const matching = (node, text) => [...node.querySelectorAll('*')].reverse().find(el => norm(el.textContent).includes(text) && norm(el.textContent).length < 220);
const slot = (node, name, text) => { if (!node) throw new Error(`Missing source landmark ${name}`); node.setAttribute('data-slot', name); if (text !== undefined) node.textContent = text; return node; };
const action = (node, name) => { if (node) node.setAttribute('data-action', name); return node; };
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const styles = [];
let styleIndex = 0;
const documents = {};
const manifest = {sources:{},assets:{}};

for (const [name, folder] of Object.entries(pages)) {
  const bytes = fs.readFileSync(path.join(source, folder + '.html'));
  manifest.sources[name] = {file:`frontend/stitch/source/${folder}.html`,sha256:hash(bytes)};
  documents[name] = parseHTML(bytes.toString('utf8')).document;
}
const document = documents.home;
const configText = document.querySelector('#tailwind-config').textContent.trim()
  .replace(/^tailwind\.config\s*=\s*/, '').replace(/;\s*$/, '');
const config = JSON.parse(configText);
const host = document.createElement('div');
host.id = 'stitch-views';
document.querySelector('main').replaceWith(host);

function template(name, node) {
  const t = document.createElement('template');
  t.setAttribute('data-template', name);
  t.innerHTML = node.outerHTML;
  document.body.append(t);
}
function timelineControls(main) {
  const heading=leaf(main,'Business timeline').parentElement;
  heading.setAttribute('data-layout','timeline-heading');
  const count=leaf(main,'Chronological Ledger Trace')||leaf(main,'3 events synchronized');
  if(count)slot(count,'event-count','0 source events');
  const toggle=document.createElement('button');toggle.type='button';toggle.className='stitch-text-action';
  toggle.hidden=true;toggle.setAttribute('aria-expanded','false');action(toggle,'toggle-timeline');slot(toggle,'timeline-toggle','Show all');heading.append(toggle);
  const note=document.createElement('p');note.className='font-body-sm text-body-sm text-text-muted';slot(note,'timeline-note','');heading.after(note);
}
function fullAnswer(main) {
  const details=document.createElement('details');details.className='stitch-full-answer';details.hidden=true;slot(details,'answer-details');
  const summary=document.createElement('summary');summary.textContent='Full answer';
  const answer=document.createElement('p');slot(answer,'answer','');details.append(summary,answer);
  main.querySelector('[data-slot="explanation"]').after(details);
}
function prepareRadar(main) {
  const judgmentLabel=[...main.querySelectorAll('*')].reverse().find(node=>/sg batch payments v2\.3.*current judgment/i.test(norm(node.textContent))&&norm(node.textContent).length<100);
  if(judgmentLabel)judgmentLabel.textContent='Current judgment';
  slot(main.querySelector('h2'), 'query', 'Submit a question to begin.');
  slot(main.querySelector('h1'), 'headline', 'Your judgment will appear here.');
  slot(matching(main,'A recovery report is available'), 'explanation', 'Only evidence returned by the current request is shown.');
  slot(leaf(main,'Pending confirmation'), 'verdict', 'Waiting for query');
  const timeline = leaf(main,'Business timeline').parentElement.parentElement.children[1];
  const item = timeline.children[0].cloneNode(true);
  const metadata = item.querySelector('.uppercase');
  slot(metadata, 'event-meta');
  const metaRow = metadata.parentElement.parentElement;
  for (const sibling of [...metaRow.children]) if (!sibling.contains(metadata)) sibling.remove();
  for (const image of item.querySelectorAll('img')) image.remove();
  const paragraphs = item.querySelectorAll('p');
  slot(paragraphs[0], 'event-title'); slot(paragraphs[1], 'event-quote');
  template('timeline', item);
  slot(timeline, 'timeline'); timeline.replaceChildren();
  timelineControls(main);
  const needs = leaf(main,'Needs confirmation').parentElement.parentElement;
  slot(needs,'needs'); needs.hidden = true;
  slot(needs.querySelector('p'),'needs-content','');
  slot([...needs.querySelectorAll('button')].find(b=>b.textContent.includes('Source difference')),'pending-label','Pending evidence checks');
  action([...needs.querySelectorAll('button')].find(b=>b.textContent.includes('Inspect evidence')),'open-first');
  const evidenceButton = [...main.querySelectorAll('button')].find(b=>b.textContent.includes('[1] Slack'));
  const list = evidenceButton.parentElement;
  slot(list,'evidence-list'); list.replaceChildren();
  action([...main.querySelectorAll('button')].find(b=>b.textContent.includes('Open Evidence Passport')),'open-first');
  action([...main.querySelectorAll('button')].find(b=>b.textContent.includes('Edit question')),'edit');
  slot(matching(main,'Bounded authorised selection'), 'coverage', 'Current authorised selection.');
  slot(leaf(main,'Employee').nextElementSibling,'employee','—');
  slot(leaf(main,'Permission version').nextElementSibling,'epoch','—');
  slot(leaf(main,'Three illustrative records'),'evidence-caption','Current request evidence');
}
function preparePassport(main) {
  slot(leaf(main,'Pending confirmation'),'verdict','Waiting for query');
  slot(main.querySelector('#claim-title'),'claim','Select an evidence source.');
  slot(main.querySelector('#claim-subtext'),'claim-scope','This passport shows the selected source and its current access metadata.');
  slot(main.querySelector('#citation-source'),'citation-source','Source');
  slot(main.querySelector('#citation-quote'),'quote','');
  slot(main.querySelector('#val-version'),'doc-version','—');
  slot(main.querySelector('#val-time'),'doc-time','—');
  slot(leaf(main,'Needs corroboration'),'doc-access-status','Checking access');
  const indexed = leaf(main,'Indexed at'); slot(indexed.nextElementSibling,'doc-indexed','—');
  const basis = leaf(main,'Access basis'); slot(basis.nextElementSibling,'doc-access','—');
  slot(leaf(main,'Live source status').nextElementSibling,'doc-source-status','Unknown');
  const drawer=main.querySelector('#evidence-drawer');slot(drawer,'passport-panel');drawer.tabIndex=-1;drawer.setAttribute('aria-label','Evidence Passport');
  main.querySelector('[class~="xl:col-span-7"]')?.setAttribute('data-layout','passport-context');
  slot(drawer.querySelector('h3'),'passport-heading','Evidence Passport');
  slot(leaf(main,'Selected Claim'),'source-heading','Selected source');
  const panel = main.querySelector('#technical-panel'); slot(panel,'technical',''); panel.classList.remove('hidden');panel.hidden = true;
  const technicalButton = [...main.querySelectorAll('button')].find(b=>b.textContent.includes('Technical details'));
  action(technicalButton,'technical');
  technicalButton.setAttribute('aria-expanded','false');technicalButton.setAttribute('aria-controls','stitch-passport-technical-panel');
  action([...main.querySelectorAll('button')].find(b=>b.textContent.trim()==='close'),'back-radar');
  [...main.querySelectorAll('button')].find(b=>b.textContent.trim()==='close').setAttribute('aria-label','Close Evidence Passport');
  action([...main.querySelectorAll('button')].find(b=>b.textContent.includes('Back to judgment')),'back-radar');
  const original=action([...main.querySelectorAll('button')].find(b=>b.textContent.includes('Open original')),'original');original.hidden=true;
  original.replaceChildren(document.createTextNode('Open in source ↗'));
  const originalEvents=[...main.querySelectorAll('[id^="item-timeline-"]')];
  let backgroundTimeline=originalEvents[0].parentElement;
  while(!originalEvents.every(node=>backgroundTimeline.contains(node)))backgroundTimeline=backgroundTimeline.parentElement;
  slot(backgroundTimeline,'timeline'); backgroundTimeline.replaceChildren();
  timelineControls(main);
  leaf(main,'Rev 04-B')?.remove();
  matching(main,'HASH: 9f8a')?.parentElement.remove();
  matching(main,'Citation and access checks do not verify every claim.')?.parentElement.remove();
  for(const node of [...main.querySelectorAll('*')].filter(node=>node.children.length===0&&/FIN.*SLA|Immutable \(4 Nodes\)/.test(norm(node.textContent))))node.closest('div.bg-surface-card')?.remove();
  slot(matching(main,'Full service recovery is not yet confirmed.'),'headline','Your current judgment.');
  slot(matching(main,'A recovery report is available.'),'explanation','');
  slot(leaf(main,'Has SG Batch Payments v2.3 fully recovered?'),'query','Current query');
  const needs = leaf(main,'Needs confirmation').parentElement.parentElement;
  slot(needs,'needs'); slot(needs.querySelector('p'),'needs-content',''); needs.hidden = true;
  for (const n of [...main.querySelectorAll('*')].filter(n=>n.children.length===0 && /9f8a|FIN-SLA|Immutable \(4 Nodes\)|SOC2|Section 4\.12/.test(n.textContent))) n.textContent='Current source scope';
}
function prepareSecurity(main) {
  leaf(main,'SG Batch Payments v2.3').textContent='Source binding change';
  const selector = main.querySelector('#employeeSelectorBtn');
  const select = document.createElement('select'); select.className=selector.className; slot(select,'employee-select'); selector.replaceWith(select);
  select.parentElement.setAttribute('data-layout','employee-control');
  select.closest('div.bg-surface-card')?.setAttribute('data-layout','employee-toolbar');
  slot(main.querySelector('#currentVersionTag'),'epoch','—');
  const before = [...main.querySelectorAll('h2')].find(h=>h.textContent.trim()==='Authorised selection').parentElement;
  slot(before.querySelector('.font-display'),'before-count','—');
  const beforeList = before.nextElementSibling; slot(beforeList,'before-bindings'); beforeList.replaceChildren();
  slot(main.querySelector('#recordsCount'),'after-count','—');
  const afterList = main.querySelector('#recordsCount').parentElement.parentElement.nextElementSibling;
  slot(afterList,'after-bindings'); afterList.replaceChildren();
  const sourceBinding = leaf(main,'Source binding: Slack').parentElement.parentElement;
  const bindingSelect = document.createElement('select'); bindingSelect.className=sourceBinding.className; slot(bindingSelect,'binding-select'); sourceBinding.replaceWith(bindingSelect);
  action(main.querySelector('#revokeButton'),'binding'); slot(main.querySelector('#revokeButtonText'),'binding-label','Choose a binding');
  action(main.querySelector('#runQueryBtn'),'query-employee');
  slot(main.querySelector('#statusBanner'),'permission-feedback','Select an employee to inspect current permissions.');
  slot(matching(main,'Permission version 5'),'before-epoch','Permission version —');
  slot(matching(main,"Remove Jax's Slack source binding"),'binding-description','Change the selected employee source binding.');
  const deliveryTitle=[...main.querySelectorAll('h2')].find(node=>norm(node.textContent)==='Check every delivery path');
  for(const card of deliveryTitle.parentElement.parentElement.parentElement.querySelector('.grid').children)card.firstElementChild.setAttribute('data-layout','delivery-heading');
}
function prepareAudit(main) {
  const input=main.querySelector('#keyword-search'); slot(input,'audit-query'); input.value='';
  for (const [label,name] of [['User:','audit-user'],['Request:','audit-request']]) {
    const text=leaf(main,label); if (!text) continue;
    const holder=text.parentElement; const field=document.createElement('input'); field.type='text'; field.placeholder=label.startsWith('User')?'User ID (optional)':'Request ID (optional)'; field.className='bg-transparent outline-none min-w-0 w-full'; slot(field,name); holder.replaceChildren(field);
  }
  action([...main.querySelectorAll('button')].find(b=>b.textContent.includes('Search audit')),'audit-search');
  action([...main.querySelectorAll('button')].find(b=>b.textContent.includes('Export redacted JSON')),'audit-export');
  const time=[...main.querySelectorAll('button')].find(b=>b.textContent.includes('Time range:')); if(time){time.textContent='All recorded times';time.disabled=true;}
  const search=main.querySelector('[data-action="audit-search"]');
  const consoleCard=input.parentElement.parentElement;
  const form=document.createElement('form');form.className='stitch-audit-filter';slot(form,'audit-form');
  form.innerHTML='<div class="stitch-audit-scope"><span>1</span>Scope</div>';
  for(const [name,label] of [['audit-query','Keywords'],['audit-user','User ID'],['audit-request','Request ID']]){
    const field=main.querySelector(`[data-slot="${name}"]`),wrap=document.createElement('label');wrap.className='stitch-audit-field';
    const caption=document.createElement('span');caption.textContent=label;wrap.append(caption,field);form.append(wrap);
  }
  const range=document.createElement('span');range.className='stitch-audit-range';range.textContent='All recorded times';
  search.type='submit';search.classList.remove('ml-auto','lg:ml-0');form.append(range,search);
  consoleCard.className='stitch-audit-console';consoleCard.replaceChildren(form);
  const events=main.querySelector('#events-container'); slot(events,'events'); events.replaceChildren();
  slot(leaf(main,'3 found'),'events-count','0 found');
  const h=main.querySelector('h2'); const details=h.parentElement.parentElement.parentElement;
  slot(details,'audit-detail');
  slot(details.children[1],'audit-facts'); details.children[1].replaceChildren();
  const answerLabel=leaf(details,'Recorded answer');
  const answerBlock=answerLabel.parentElement.parentElement; slot(answerBlock.children[1],'audit-answer','Choose an event to view its released details.');
  const mask=matching(answerBlock,'Masked for unauthorized auditors'); if(mask) slot(mask,'audit-mask','Current access applies');
  slot(main.querySelector('tbody'),'audit-evidence'); main.querySelector('tbody').replaceChildren();
  const question=document.createElement('div');question.className='stitch-audit-question';question.innerHTML='<span class="font-label-sm text-label-sm text-text-muted">Recorded question</span><p data-slot="audit-question"></p>';answerBlock.before(question);
  const authorisations=document.createElement('details');authorisations.className='stitch-audit-authorisations';authorisations.innerHTML='<summary>Recorded authorisation checks</summary><div data-slot="audit-authorisations"></div>';answerBlock.after(authorisations);
  slot(leaf(details,'REC-ID #883921'),'audit-id','Request details');
  const itemCount=leaf(details,'3 items'); if(itemCount)slot(itemCount,'audit-evidence-count','0 items');
  const frequency=leaf(main,'Query Frequency Spike'); if(frequency)frequency.parentElement.parentElement.remove();
  for (const n of [...main.querySelectorAll('*')].filter(n=>/Local audit chain.*valid/i.test(norm(n.textContent)) && norm(n.textContent).length<85 && ![...n.children].some(child=>/Local audit chain.*valid/i.test(norm(child.textContent))))) slot(n,'integrity','Audit chain not checked');
}

for (const [name, doc] of Object.entries(documents)) {
  // The home main was detached when creating the view host; retrieve it from a fresh source parse.
  const main=name==='home'?parseHTML(fs.readFileSync(path.join(source,pages.home+'.html'),'utf8')).document.querySelector('main'):doc.querySelector('main');
  main.setAttribute('data-page',name); main.hidden=name!=='home';
  if(name==='home'){
    slot(main.querySelector('#queryInput'),'question'); main.querySelector('#queryInput').value='';
    main.querySelector('#queryInput').placeholder='Ask a business question…';
    main.querySelector('#queryInput').nextElementSibling?.setAttribute('data-layout','query-toolbar');
    const dataset=[...main.querySelectorAll('button')].find(b=>b.textContent.includes('OrgForge demo'));
    const select=document.createElement('select'); select.className=dataset.className; slot(select,'corpus');dataset.replaceWith(select);
    const ask=action([...main.querySelectorAll('button')].find(b=>b.textContent.includes('Ask ContextLedger')),'ask');slot(ask.querySelector('span'),'ask-label','Ask ContextLedger');
    ask.querySelector('.material-symbols-outlined').setAttribute('data-slot','ask-icon');
    const heading=main.querySelector('h2').parentElement.parentElement;heading.setAttribute('data-layout','composer-heading');heading.parentElement.setAttribute('data-layout','composer-card');
    const guide=[...main.querySelectorAll('h2')].find(node=>norm(node.textContent)==='How to explore an answer').closest('[class~="lg:col-span-7"]');
    const examples=[...main.querySelectorAll('h2')].find(node=>norm(node.textContent)==='Try a demo question').closest('[class~="lg:col-span-5"]');
    guide.classList.add('stitch-home-guide');examples.classList.add('stitch-home-examples');guide.parentElement.setAttribute('data-layout','home-support');
    for(const text of ['Synthesized','Tickets & Commits','Evidence Passport']){
      const badge=[...guide.querySelectorAll('span.rounded-full')].find(node=>norm(node.textContent).includes(text));
      if(badge){badge.classList.add('stitch-guide-step-badge');badge.parentElement.classList.add('stitch-guide-step-heading');}
    }
    const demoQuestions=['What is TitanDB used for?','What happened during the ENG-195 / PR-135 review?','Which parts of the ENG-195 / PR-135 outcome remain unconfirmed?'];
    for(const [index,b] of [...main.querySelectorAll('button[onclick^="populatePrompt"]')].entries()){const m=b.getAttribute('onclick').match(/populatePrompt\(['"](.+?)['"]\)/); if(m){const question=demoQuestions[index]||m[1];leaf(b,m[1]).textContent=question;b.dataset.question=question;action(b,'example');}}
    const planning=leaf(main,'Query planning enabled');
    if(planning){const control=document.createElement('label');control.className='stitch-planning';control.innerHTML='<span>Query planning</span><input type="checkbox" role="switch" aria-label="Query planning" data-slot="planning-toggle"><span class="stitch-switch-track" aria-hidden="true"></span><span data-slot="planning-label">Off</span>';planning.parentElement.replaceWith(control);}
    const illustration=guide.querySelector('img');illustration.src='/static/stitch/assets/vectorized.svg.svg';illustration.alt='Source records connected to a business judgment, timeline and Evidence Passport';illustration.classList.add('stitch-guide-image');
  }
  if(name==='radar')prepareRadar(main);
  if(name==='passport')preparePassport(main);
  if(name==='radar'||name==='passport')fullAnswer(main);
  if(name==='security')prepareSecurity(main);
  if(name==='audit')prepareAudit(main);
  leaf(main,'Audit Agent Healthy')?.remove();
  if(['radar','passport'].includes(name)){
    const query=main.querySelector('[data-slot="query"]');
    let card=query.parentElement;
    while(card&&!card.classList.contains('bg-surface-card'))card=card.parentElement;
    if(card)card.setAttribute('data-layout','question-card');
  }
  if(name==='radar')main.querySelector('h1').closest('.bg-surface-card').setAttribute('data-layout','judgment-card');
  // Remove the reference-only Chinese footer cards from the imported views.
  for(const node of [...main.querySelectorAll('*')].filter(node=>node.children.length===0&&/\p{Script=Han}/u.test(node.textContent))){
    if(!main.contains(node))continue;
    const grid=node.closest('[class~="lg:grid-cols-4"],[class~="md:grid-cols-4"]');
    if(grid){const parent=grid.parentElement;grid.remove();if(!norm(parent.textContent)&&!parent.children.length)parent.remove();}else node.remove();
  }
  const banner=main.firstElementChild.firstElementChild;banner.setAttribute('data-layout','workspace-banner');
  const caption=document.createElement('span');caption.className='stitch-mobile-scope';caption.textContent='Offline ACL snapshot';banner.firstElementChild.lastElementChild.append(caption);
  const noticeHost=document.createElement('div');noticeHost.setAttribute('data-slot','notice-host');noticeHost.hidden=true;
  if(name==='home')main.querySelector('[data-slot="question"]').after(noticeHost);
  if(name==='radar')main.querySelector('h1').parentElement.append(noticeHost);
  if(name==='passport')main.querySelector('[data-slot="passport-panel"]').children[0].after(noticeHost);
  if(name==='security')main.querySelector('[data-action="binding"]').after(noticeHost);
  if(name==='audit')main.querySelector('h1').parentElement.parentElement.after(noticeHost);
  host.append(main);
}

// Retain original shell geometry; replace only the identity controls and unsupported claims.
const profile=document.querySelector('header [class*="cursor-pointer"]');
if(profile){const select=document.createElement('select');select.className='bg-transparent font-label-sm text-label-sm outline-none max-w-[220px]';select.setAttribute('aria-label','Current identity');slot(select,'identity-select');profile.replaceChildren(select);}
slot(leaf(document.querySelector('header'),'Workspace'),'breadcrumb','Workspace');
for(const a of document.querySelectorAll('aside a[data-path]')){
  const name={'workspace':'home','audit-trail':'audit','manage-permissions':'security'}[a.dataset.path];
  if(name){a.href='#'+name;a.dataset.nav=name;if(name!=='home'){a.dataset.roleRequired=name==='security'?'admin':'audit';a.hidden=true;}}
  else a.remove();
}
for(const button of document.querySelectorAll('button')) if(norm(button.textContent)==='Export Snapshot')button.remove();
for(const button of document.querySelectorAll('button[data-action]')){
  if(['example','technical','toggle-timeline'].includes(button.dataset.action))continue;
  const labels=[...button.children].filter(node=>node.tagName==='SPAN'&&!node.classList.contains('material-symbols-outlined'));
  for(const child of [...button.childNodes].filter(node=>node.nodeType===3&&norm(node.textContent))){const label=document.createElement('span');label.textContent=norm(child.textContent);child.replaceWith(label);labels.push(label);}
  if(labels.length){button.classList.add('stitch-fit-action');labels.forEach(label=>label.classList.add('stitch-action-label'));}
}
for(const button of document.querySelectorAll('button')) if(!button.hasAttribute('data-action'))button.disabled=true;
const replacements={
  'Live Synced':'Offline snapshot','Acme Corp Enterprise':'OrgForge demo workspace',
  'Ledger Node Status':'Source ACL snapshot','Active':'Offline','© ContextLedger v2.4':'ContextLedger · Demo',
  'SG BATCH PAYMENTS V2.3 · CURRENT JUDGMENT':'CURRENT JUDGMENT',
  'SG Batch Payments v2.3 · Current Judgment':'Current judgment',
  '4 Ingestion Feeds → Cryptographic Passport':'4 source feeds → Evidence Passport',
  'Click another citation [1], [2], [3] to change the selected evidence passport.':'Select another available citation to inspect a different source.',
  'Enterprise Evidence Vault Active':'Evidence workspace','Audit Agent Healthy':'Isolated demo',
  'All regulatory audits and decision records are immutably signed.':'Current identity and source ACL snapshot apply.',
  'Evidence synchronizing with SHA-256 cryptochain.':'Offline source ACL snapshot. Live permission sync is not enabled.',
  'SHA-256 Validated':'Source scope applies','SHA-256 Merkle verified':'Recorded evidence versions',
  'Verified Record':'Referenced source','Verified Digest':'Source digest','SIG_VALID':'Recorded digest','Source-reported':'Cited source',
  'Cryptographic Evidence Vector [1]':'Source reference','Immutable Log':'Source context',
  'Zero Hallucination':'Authorised evidence','All 3 Channels Sanitized':'Current access applies',
  'Live Clean':'Re-query','Zero-trust hot swap ready':'Next request uses current permissions',
  'authorised evidence records':'active source bindings',
  'Counts are synthetic scenario values, not blocked-document statistics.':'Counts show actual source bindings, not document search results.',
  'ILLUSTRATIVE SAVED STATE':'Permission change',
  'Original excerpt · Illustrative demo data':'Original source text',
  'Access Level: Enterprise Tier 1':'Current session scope',
  'Encrypted':'Offline scope','Node 0x8F92':'Local audit'
};
replacements['Historical query, answer, and evidence details are redacted when current access or the recorded version cannot be verified. Table illustrates per-record visibility; current API may redact the complete event evidence list when operating in zero-trust isolation.']='Current access, recorded versions and content hashes are checked together. If any recorded source cannot be verified, the request evidence and authorisation details are withheld. Events without recorded evidence are labelled separately.';
for(const node of document.querySelectorAll('*')){
  for (const child of [...node.childNodes].filter(child=>child.nodeType===3)) {
    const text=norm(child.textContent);
    if(replacements[text])child.textContent=replacements[text];
    else if(/Offline snapshot stored/.test(text))child.textContent='Source ACL snapshot';
    else if(/99\.8%|480ms|Zero cache leakage|14 nodes indexed|18 Source Node/.test(text))child.textContent='Current access applies';
    else if(/confidence ratings|confidence bands/.test(text))child.textContent='Read the cited judgment and its explicit evidence limits.';
    else if(/Cryptographic Passport|Cryptographic Evidence|signed Slack threads|cryptochain/i.test(text))child.textContent='Inspect the source text, recorded versions and current access metadata.';
  }
  for(const attr of [...node.attributes])if(attr.name.startsWith('on'))node.removeAttribute(attr.name);
  if(node.id){node.setAttribute('data-original-id',node.id);node.id=`stitch-${node.closest('[data-page]')?.dataset.page||'shell'}-${node.id}`;}
  if(node.hasAttribute('style')){const cls=`stitch-inline-${++styleIndex}`;styles.push(`.${cls}{${node.getAttribute('style')}}`);node.classList.add(cls);node.removeAttribute('style');}
}
for(const script of [...document.querySelectorAll('script')])script.remove();
for(const style of [...document.querySelectorAll('style')]){styles.push(style.textContent);style.remove();}
const notice=document.createElement('div');notice.id='stitch-notice';notice.setAttribute('role','status');notice.hidden=true;document.body.append(notice);
const app=document.createElement('script');app.src='/static/stitch/app.js?v=18';app.defer=true;document.head.append(app);
for(const href of ['/static/stitch/fonts.css','/static/stitch/design.css','/static/stitch/responsive.css']){const link=document.createElement('link');link.rel='stylesheet';link.href=href+'?v=8';document.head.append(link);}
document.title='ContextLedger · Stitch workspace';
const logo=document.querySelector('img[alt="ContextLedger Logo"]');logo.src='/static/stitch/assets/contextledger-logo.svg';logo.className='h-10 w-10 shrink-0 object-contain';logo.width=40;logo.height=40;
const icon=document.createElement('link');icon.rel='icon';icon.type='image/svg+xml';icon.href='/static/stitch/assets/contextledger-logo.svg';document.head.append(icon);

async function localizeAssets(){
  fs.mkdirSync(path.join(out,'assets'),{recursive:true});
  const urls=new Map();
  for(const img of document.querySelectorAll('img[src^="http"]')){const url=img.getAttribute('src');if(!urls.has(url))urls.set(url,[]);urls.get(url).push(img);}
  async function download(url,ext){const file=hash(url).slice(0,20)+ext;const target=path.join(out,'assets',file);if(!fs.existsSync(target)){const response=await fetch(url,{signal:AbortSignal.timeout(25000)});if(!response.ok)throw new Error(`Asset ${response.status}: ${url}`);fs.writeFileSync(target,Buffer.from(await response.arrayBuffer()));}manifest.assets[file]=url;return '/static/stitch/assets/'+file;}
  const entries=[...urls];let next=0;
  await Promise.all(Array.from({length:4},async()=>{while(next<entries.length){const [url,nodes]=entries[next++];const local=await download(url,'.png');for(const img of nodes)img.src=local;}}));
  let fonts='';
  for(const link of [...document.querySelectorAll('link[rel="stylesheet"][href^="https://fonts.googleapis.com"]')]){
    const url=link.href;const response=await fetch(url,{signal:AbortSignal.timeout(25000),headers:{'User-Agent':'Mozilla/5.0'}});if(!response.ok)throw new Error(`Font stylesheet ${response.status}`);
    let css=await response.text();for(const m of [...css.matchAll(/url\((https:\/\/[^)]+)\)/g)]){const local=await download(m[1],path.extname(new URL(m[1]).pathname)||'.woff2');css=css.replaceAll(m[1],local);}fonts+=css+'\n';link.remove();
  }
  for(const link of [...document.querySelectorAll('link[rel="preconnect"]')])link.remove();
  fs.writeFileSync(path.join(out,'fonts.css'),fonts);
}
(async()=>{
  await localizeAssets();
  const auditMain=document.querySelector('[data-page="audit"]');
  const first=auditMain.querySelector('.stitch-audit-console');
  const nodes=[];for(let node=first;node;node=node.nextSibling)nodes.push(node);
  const host=document.createElement('div');host.innerHTML=fs.readFileSync(path.join(__dirname,'audit-console.html'),'utf8');
  const legacy=document.createElement('section');legacy.dataset.slot='audit-legacy';legacy.hidden=true;
  first.before(host.firstElementChild,legacy);for(const node of nodes)legacy.append(node);
  const change=(old,value)=>{const node=leaf(auditMain,old);if(node)node.textContent=value;};
  change('Evidence workspace','Audit workspace');change('Current identity and source ACL snapshot apply.','Recorded activity, permission changes and operational events.');
  change('Governance · Current Access Checks Apply','Governance · Recorded Activity');change('Source scope applies','Administrator audit view');
  change('Trace a request, its recorded evidence versions, and authorisation context with cryptographic provenance.','Investigate information access, permission changes, document updates and unauthorised attempts.');
  manifest.auditConsole={file:'frontend/stitch/audit-console.html',sha256:hash(fs.readFileSync(path.join(__dirname,'audit-console.html')))};
  fs.writeFileSync(path.join(out,'index.html'),'<!doctype html>\n'+document.documentElement.outerHTML);
  fs.writeFileSync(path.join(out,'source-manifest.json'),JSON.stringify(manifest,null,2)+'\n');
  const temp=process.env.STITCH_BUILD_TMP||path.join(require('node:os').tmpdir(),'contextledger-stitch-compile');fs.mkdirSync(temp,{recursive:true});
  config.content=[path.join(source,'*.html'),path.join(out,'app.js')];
  fs.writeFileSync(path.join(temp,'tailwind.config.cjs'),'module.exports='+JSON.stringify(config));
  fs.writeFileSync(path.join(temp,'input.css'),'@tailwind base;\n@tailwind components;\n@tailwind utilities;\n'+styles.join('\n'));
  const cli=require.resolve('tailwindcss/lib/cli.js');
  const result=spawnSync(process.execPath,[cli,'-c',path.join(temp,'tailwind.config.cjs'),'-i',path.join(temp,'input.css'),'-o',path.join(out,'design.css'),'--minify'],{stdio:'inherit'});
  if(result.status!==0)throw new Error('Tailwind build failed');
  console.log('Imported five supplied page bodies; original UI files were not edited.');
})().catch(error=>{console.error(error);process.exitCode=1;});
