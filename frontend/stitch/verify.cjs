// Browser contract checks use fixtures; no real user permissions are changed.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require('playwright');
const base=process.env.STITCH_BASE_URL||'http://127.0.0.1:17860';
const sourceText='<img src=x onerror="window.stitchInjected=true"> Payments are processing again.\n\n'+('A long original-source paragraph checks the full-screen scroll area, technical details and bottom actions. Continue monitoring the incident before confirming recovery.\n\n'.repeat(20));
const employee={id:'member',name:'Radar Engineer（演示员工）',role:'member',epoch:5,enabled:true};
const admin={id:'admin',name:'ContextLedger 管理员',role:'admin',epoch:1,enabled:true};
let actor=employee, confirmed=false, deniedDoc=false, binding=true, employeeEpoch=5,askDelay=250,failAsk=false;
let docDelays={},docFailures={},docURL=null;
const changes=[],errors=[];
const planningRequests=[];
const evidence=[{citation_id:1,corpus:'orgforge',doc_id:'slack-1',title:'Recovery report',source:'slack',version:'v1'},{citation_id:2,corpus:'orgforge',doc_id:'jira-2',title:'Incident record',source:'jira',version:'v2'},...Array.from({length:10},(_,i)=>({citation_id:i+3,corpus:'orgforge',doc_id:'source-'+i,title:'Postmortem: P1 incident · '+('Regional payment processing and recovery validation report · '.repeat(4))+i,source:'confluence',version:'v1'}))];
const visibleRequestId='req-visible-20261014-aaaaaaaa-1234567890abcdef';
const viewportWidths=[1600,1440,1280,1199,1024,1023,900,820,768,767,390,360,320];
const response=()=>({decision:'answered',provider:'fixture',request_id:'req-1',answer:'Recovery requires monitoring validation. [1] [2]',evidence,
  radar:{coverage:{documents:12,truncation_reasons:[]},event_candidates:evidence.slice(0,8).map((hit,i)=>({citation_id:hit.citation_id,event_time:i===1?null:'2026-10-14T09:40:00Z',type:'source_report',quote:'Operations reported recovery. '+('Formal monitoring and incident review remain necessary. '.repeat(4))}))},
  radar_presentation:{status:confirmed?'confirmed':'pending_confirmation',headline:confirmed?'Service recovery confirmed.':'Full recovery is not yet confirmed.',explanation:'A report exists. Review the formal monitoring criteria.',citation_ids:[1,2],needs_confirmation:confirmed?[]:[{item:'Confirm monitoring validation.',citation_ids:[2]}]}});

(async()=>{
  const options={headless:true};
  if(process.env.STITCH_BROWSER_PATH)options.executablePath=process.env.STITCH_BROWSER_PATH;
  else if(process.platform==='win32')options.executablePath='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  options.args=['--no-sandbox','--disable-gpu'];
  const browser=await chromium.launch(options);
  try {
    const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
    const page=await context.newPage();
    await page.addInitScript(()=>{window.stitchMotions=[];const original=Element.prototype.animate;Element.prototype.animate=function(frames,options){window.stitchMotions.push({page:this.closest('[data-page]')?.dataset.page,slot:this.dataset.slot,frames,options});return original.call(this,frames,options);};});
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/api/**',async route=>{
      const request=route.request(),url=new URL(request.url());let data;
      if(request.method()==='POST')assert.equal(request.headers()['x-csrf-token'],'test-csrf');
      if(url.pathname==='/api/session')data={user:actor,csrf:'test-csrf',demo_mode:true,workflows:{planner_configured:true,planner_enabled:false}};
      else if(url.pathname==='/api/demo/accounts')data=[admin,{...employee,epoch:employeeEpoch,initial_source:true}];
      else if(url.pathname==='/api/demo/select'){actor=request.postDataJSON().user_id==='admin'?admin:{...employee,epoch:employeeEpoch};data={ok:true};}
      else if(url.pathname==='/api/corpora')data=actor.role==='admin'?[]:[{id:'orgforge',label:'OrgForge demo'}];
      else if(url.pathname==='/api/ask'){assert.equal(request.postDataJSON().corpus,'orgforge');assert.equal(request.postDataJSON().output_language,'en');planningRequests.push(request.postDataJSON().planning);if(askDelay)await new Promise(resolve=>setTimeout(resolve,askDelay));if(failAsk){await route.fulfill({status:503,contentType:'application/json',body:'{}'});return;}data=response();}
      else if(url.pathname==='/api/doc'){const id=url.searchParams.get('doc_id');if(docDelays[id])await new Promise(resolve=>setTimeout(resolve,docDelays[id]));if(docFailures[id]){await route.fulfill({status:docFailures[id],contentType:'application/json',body:'{}'});return;}data=deniedDoc?{available:false}:{available:true,doc:{title:id==='jira-2'?'Incident record':'Recovery report',text:sourceText,source:'slack',source_url:docURL,version:'v1',ts:'2026-10-14T09:40:00Z',indexed_at:'2026-10-14T10:00:00Z',acl_basis:'administrator adjusted ACL; previous provenance retained in document history',metadata:{acl_provenance:{kind:'administrator_adjustment',previous_version:'v0'},source_acl_reference:{source_acl_basis:'unverified operator note'}},content_hash:'ab'.repeat(32),source_check:'unknown'}};}
      else if(url.pathname==='/api/admin/users'){assert.equal(actor.role,'admin');data=[admin,{...employee,epoch:employeeEpoch,bindings:[{corpus:'orgforge',principal_id:'slack:jax',enabled:binding}],restrictions:[]}];}
      else if(url.pathname==='/api/admin/principals')data=[{corpus:'orgforge',principal_id:'slack:jax',name:'Slack · Jax'}];
      else if(url.pathname==='/api/admin/permissions'){assert.equal(actor.role,'admin');const body=request.postDataJSON();changes.push(body);binding=body.enabled;employeeEpoch++;data={ok:true};}
      else if(url.pathname==='/api/audit')data={integrity:{valid:true},events:[{request_id:'req-redacted',user_id:'member',event_type:'answer',permission_epoch:5,timestamp:'2026-10-14T10:01:00Z',redacted:true,evidence_visibility:'current_access_unavailable',query:'HIDDEN QUERY',authorization_decisions:[{document_id:'HIDDEN AUTH'}],question:'HIDDEN QUESTION',answer:'HIDDEN ANSWER',evidence:[{doc_id:'HIDDEN DOCUMENT'}]},{request_id:visibleRequestId,user_id:'admin',event_type:'permission_change',permission_epoch:1,policy_version:'snapshot-acl-and-local-deny-v1',timestamp:'2026-10-14T10:04:00Z',redacted:false,evidence_visibility:'not_recorded',answer:'Permission change saved.',evidence:[]}]};
      else throw new Error('Unexpected API '+url.pathname);
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(base+'/static/stitch/index.html');
    await page.waitForFunction(()=>document.querySelector('[data-page=home] [data-slot=corpus]').options.length===2);
    const planning=page.getByRole('switch',{name:'Query planning'});
    assert.equal(await planning.isChecked(),false);
    await planning.check();await page.waitForTimeout(5200);
    assert.equal(await planning.isChecked(),true,'Session polling must preserve user choice');
    assert.equal(await page.locator('.stitch-guide-image').getAttribute('src'),'/static/stitch/assets/vectorized.svg.svg');
    assert.equal(await page.locator('[data-action=legacy]').count(),0);
    assert.equal((await page.locator('body').innerText()).includes('Isolated demo'),false);
    assert.deepEqual(await page.evaluate(()=>['[data-slot="corpus"]','.stitch-planning','[data-action="ask"]'].map(selector=>document.querySelector(selector).getBoundingClientRect().height)),[44,44,44]);
    if(await page.evaluate(()=>CSS.supports('appearance','base-select'))){assert.equal(await page.locator('[data-slot=corpus]').evaluate(n=>getComputedStyle(n,'::picker(select)').borderRadius),'14px');}
    assert.doesNotMatch(await page.locator('body').innerText(),/[\u4e00-\u9fff]/);
    await page.fill('[data-page=home] [data-slot=question]','Has SG Batch Payments recovered?');
    await page.click('[data-page=home] [data-action=ask]');
    assert.equal(await page.locator('[data-page=home] [data-action=ask]').getAttribute('aria-busy'),'true');
    assert.equal(await page.locator('[data-page=home] [data-action=ask]').isDisabled(),true);
    await page.waitForFunction(()=>document.body.dataset.activePage==='radar');
    assert.equal(planningRequests[0],true);
    assert.equal(await page.locator('[data-page=radar] [data-slot=headline]').evaluate(n=>n===document.activeElement),true);
    assert.notEqual(await page.locator('[data-page=radar] [data-layout=question-card]').evaluate(n=>getComputedStyle(n).backgroundColor),await page.locator('[data-page=radar] [data-layout=judgment-card]').evaluate(n=>getComputedStyle(n).backgroundColor));
    assert.equal(await page.evaluate(()=>window.stitchMotions.some(m=>m.page==='radar'&&m.options.duration===200)),true);
    assert.equal(await page.locator('[data-page=radar] [data-slot=verdict]').textContent(),'Pending confirmation');
    assert.equal(await page.locator('[data-page=radar] [data-slot=needs]').isVisible(),true);
    askDelay=0;
    assert.equal(await page.locator('[data-page=radar] [data-slot=evidence-list] button').count(),12);
    assert.equal(await page.locator('[data-page=radar] [data-slot=timeline] > :visible').count(),4);
    await page.click('[data-page=radar] [data-action=toggle-timeline]');
    assert.equal(await page.locator('[data-page=radar] [data-slot=timeline] > :visible').count(),8);
    await page.click('[data-page=radar] [data-action=toggle-timeline]');
    assert.equal(await page.locator('[data-page=radar] [data-slot=timeline] > :visible').count(),4);
    await page.locator('[data-page=radar] [data-slot=evidence-list] button').first().click();
    await page.waitForFunction(()=>document.querySelector('[data-page=passport] [data-slot=doc-access-status]').textContent==='Authorised source');
    assert.equal(await page.locator('[data-slot=passport-panel]').evaluate(n=>n===document.activeElement),true);
    assert.equal(await page.evaluate(()=>window.stitchMotions.some(m=>m.slot==='passport-panel'&&m.options.duration===250)),true);
    assert.equal(await page.locator('[data-page=passport] [data-action=original]').isVisible(),false);
    assert.equal(await page.locator('[data-page=passport] [data-slot=quote]').textContent(),sourceText);
    assert.equal(await page.evaluate(()=>Boolean(window.stitchInjected)),false);
    await page.click('[data-page=passport] [data-action=technical]');
    assert.equal(await page.locator('[data-page=passport] [data-slot=technical]').isVisible(),true);
    assert.equal(await page.locator('[data-page=passport] [data-action=technical]').getAttribute('aria-expanded'),'true');
    assert.match(await page.locator('[data-page=passport] [data-slot=technical]').textContent(),/abababab/);
    const technical=JSON.parse(await page.locator('[data-page=passport] [data-slot=technical]').textContent());assert.equal(technical.acl_provenance.kind,'administrator_adjustment');assert.equal(technical.current_source_acl_basis,null);assert.equal(technical.unverified_source_acl_reference.source_acl_basis,'unverified operator note');
    assert.equal(await page.locator('[data-page=passport] [data-slot=event-count]').textContent(),'8 source events');
    assert.equal(await page.locator('[data-page=passport] [data-original-id^="item-timeline-"]').count(),0);
    for(const width of viewportWidths){
      await page.setViewportSize({width,height:1000});
      await page.waitForFunction(role=>document.querySelector('[data-page=passport] [data-slot=passport-panel]').getAttribute('role')===role,width<=1023?'dialog':'region');
      const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(size.scroll<=size.width,`Passport overflow ${JSON.stringify(size)}`);
      if(width<=1023){
        const panel=page.locator('[data-page=passport] [data-slot=passport-panel]');assert.equal(await panel.getAttribute('role'),'dialog');
        const box=await panel.boundingBox();assert.equal(Math.round(box.y),0);assert.ok(Math.abs(box.width-width)<2);
        assert.ok((await page.locator('[data-page=passport] [data-slot=claim]').boundingBox()).y<350);
      }
    }
    await page.click('[data-page=passport] [data-action=technical]');assert.equal(await page.locator('[data-page=passport] [data-slot=technical]').isVisible(),false);
    await page.click('[data-page=passport] [data-action=technical]');assert.equal(await page.locator('[data-page=passport] [data-slot=technical]').isVisible(),true);
    const focusable=await page.locator('[data-page=passport] [data-action=technical]');await focusable.focus();await page.keyboard.press('Tab');
    assert.equal(await page.locator('[data-page=passport] [data-action=back-radar]').first().evaluate(node=>node===document.activeElement),true);
    await page.keyboard.press('Escape');assert.equal(await page.locator('body').getAttribute('data-active-page'),'radar');
    assert.equal(await page.locator('[data-page=radar] [data-slot=evidence-list] button').first().evaluate(node=>node===document.activeElement),true);
    await page.setViewportSize({width:1440,height:1000});
    docDelays={'slack-1':200};await page.locator('[data-page=radar] [data-slot=evidence-list] button').first().click();
    await page.locator('[data-page=passport] [data-slot=timeline] button').nth(1).click();
    await page.waitForFunction(()=>document.querySelector('[data-page=passport] [data-slot=claim]').textContent==='Incident record');await page.waitForTimeout(250);
    assert.equal(await page.locator('[data-page=passport] [data-slot=claim]').textContent(),'Incident record');docDelays={};
    await page.click('[data-page=passport] [data-action=back-radar]');deniedDoc=true;
    await page.locator('[data-page=radar] [data-slot=evidence-list] button').last().click();
    await page.waitForFunction(()=>document.body.dataset.activePage==='home');
    assert.equal(await page.locator('[data-page=passport] [data-slot=quote]').textContent(),'—');
    assert.equal(await page.locator('[data-page=radar] [data-slot=evidence-list] button').count(),0);
    deniedDoc=false;failAsk=true;await planning.uncheck();await page.click('[data-page=home] [data-action=ask]');await page.waitForFunction(()=>document.getElementById('stitch-notice').dataset.tone==='error'&&!document.getElementById('stitch-notice').hidden);
    assert.equal(planningRequests.at(-1),false);
    assert.equal(await page.locator('#stitch-notice').evaluate(node=>getComputedStyle(node).position),'static');failAsk=false;confirmed=true;
    await page.click('[data-page=home] [data-action=ask]');await page.waitForFunction(()=>document.body.dataset.activePage==='radar');
    assert.equal(await page.locator('[data-page=radar] [data-slot=verdict]').textContent(),'Confirmed');
    assert.equal(await page.locator('[data-page=radar] [data-slot=needs]').isVisible(),false);
    await page.selectOption('[data-slot=identity-select]','admin');await page.waitForSelector('[data-nav=security]:visible');
    assert.equal(await page.locator('[data-page=radar] [data-slot=explanation]').textContent(),'');
    await page.click('[data-nav=security]');await page.waitForFunction(()=>document.querySelector('[data-page=security] [data-slot=before-count]').textContent==='1');
    await page.click('[data-page=security] [data-action=binding]');await page.waitForFunction(()=>document.querySelector('[data-page=security] [data-slot=after-count]').textContent==='0');
    assert.equal(await page.locator('[data-page=security] [data-slot=before-count]').textContent(),'1');
    assert.equal(changes[0].enabled,false);assert.equal(changes[0].user_id,'member');
    await page.click('[data-page=security] [data-action=binding]');await page.waitForFunction(()=>document.querySelector('[data-page=security] [data-slot=after-count]').textContent==='1');assert.equal(changes[1].enabled,true);
    await page.click('[data-nav=audit]');await page.click('[data-page=audit] [data-action=audit-search]');await page.waitForFunction(()=>document.querySelector('[data-page=audit] [data-slot=events-count]').textContent==='2 found');
    assert.match(await page.locator('[data-slot=audit-evidence]').textContent(),/current access could not be verified/);
    assert.equal((await page.locator('body').textContent()).includes('HIDDEN AUTH'),false);
    assert.equal((await page.locator('body').textContent()).includes('HIDDEN QUESTION'),false);
    assert.equal((await page.locator('body').textContent()).includes('HIDDEN ANSWER'),false);
    assert.equal((await page.locator('body').textContent()).includes('HIDDEN DOCUMENT'),false);
    await page.locator('[data-page=audit] [data-slot=events] button').nth(1).click();
    assert.equal(await page.locator('[data-slot=audit-evidence-count]').textContent(),'Not recorded');
    assert.match(await page.locator('[data-slot=audit-evidence]').textContent(),/did not record any evidence/);
    assert.ok((await page.locator('[data-page=audit] [data-slot=audit-id]').textContent()).length<visibleRequestId.length);
    assert.equal(await page.locator('[data-page=audit] [data-slot=audit-id]').getAttribute('title'),visibleRequestId);
    assert.match(await page.locator('[data-page=audit] [data-slot=audit-facts]').textContent(),/SGT \(UTC\+08:00\)/);
    await page.getByRole('button',{name:'Copy full request ID',exact:true}).click();await page.waitForFunction(()=>document.getElementById('stitch-notice').textContent==='Copied full identifier.');assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),visibleRequestId);
    const downloadEvent=page.waitForEvent('download');await page.click('[data-page=audit] [data-action=audit-export]');const download=await downloadEvent;assert.equal(download.suggestedFilename(),'contextledger-audit-redacted.json');
    assert.equal(fs.readFileSync(await download.path(),'utf8').includes('HIDDEN'),false);
    for(const width of viewportWidths){
      await page.setViewportSize({width,height:1000});
      for(const view of ['home','security','audit']){
        await page.click(`[data-nav=${view}]`);await page.waitForTimeout(100);
        const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(size.scroll<=size.width,`${view} overflow ${JSON.stringify(size)}`);
        const identity=await page.locator('[data-slot=identity-select]').boundingBox();assert.ok(identity.x>=0&&identity.x+identity.width<=width+1,`Identity offscreen at ${width} on ${view}`);
        assert.doesNotMatch(await page.locator('body').innerText(),/[\u4e00-\u9fff]/);
        const clipped=await page.locator('.stitch-action-label:visible').evaluateAll(nodes=>nodes.filter(n=>n.scrollWidth>n.clientWidth+2).map(n=>n.textContent));assert.deepEqual(clipped,[],`Clipped action at ${width} on ${view}`);
        if(view==='audit'){
          const fields=await page.locator('.stitch-audit-field input').evaluateAll(nodes=>nodes.map(n=>({width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height})));assert.ok(fields.every(f=>f.width>=100&&f.height>=44),`Audit input squeezed at ${width}`);
        }
        if(view==='home'&&width<768){
          const ask=await page.locator('[data-page=home] [data-action=ask]').boundingBox();assert.ok(ask.y+ask.height<=844,`Ask below first phone screen at ${width}`);
          const example=await page.locator('[data-page=home] [data-action=example]').first().boundingBox();const guide=await page.locator('.stitch-home-guide').boundingBox();assert.ok(example.y<guide.y);
        }
      }
    }
    await page.click('[data-nav=home]');
    await page.route('**/stitch/test-zoom.css*',route=>{const scale=Number(new URL(route.request().url()).searchParams.get('scale'));return route.fulfill({contentType:'text/css',body:`[data-page="home"] [data-action="ask"]{width:230px!important;max-width:100%!important;font-size:${16*scale}px!important}`});});
    for(const scale of [1.25,1.5,2]){
      await page.setViewportSize({width:Math.round(1600/scale),height:1000});
      await page.addStyleTag({url:base+`/static/stitch/test-zoom.css?scale=${scale}`});await page.waitForTimeout(120);
      const label=page.locator('[data-slot=ask-label]');assert.equal(await label.evaluate(n=>getComputedStyle(n).whiteSpace),'nowrap');assert.equal(await label.evaluate(n=>n.scrollWidth<=n.clientWidth+2),true,`Ask clips at ${scale}`);
    }
    await page.click('[data-nav=home]');await page.selectOption('[data-slot=identity-select]','member');await page.waitForFunction(()=>document.querySelector('[data-slot="corpus"]').value==='orgforge');await page.emulateMedia({reducedMotion:'reduce'});await page.fill('[data-slot=question]','Has SG Batch Payments recovered?');await page.click('[data-action=ask]');await page.waitForFunction(()=>document.body.dataset.activePage==='radar');
    const reduced=await page.evaluate(()=>window.stitchMotions.at(-1));assert.equal(reduced.options.duration,100);assert.ok(reduced.frames.every(frame=>!('transform' in frame)));
    await page.locator('[data-page=radar] [data-action=open-first]').last().click();await page.keyboard.press('Escape');assert.equal(await page.locator('body').getAttribute('data-active-page'),'radar');assert.equal(await page.evaluate(()=>document.querySelector('[data-slot="passport-panel"]').getAnimations().length),0);
    docDelays={'slack-1':250};docFailures={'slack-1':409};await page.locator('[data-page=radar] [data-action=open-first]').last().click();await page.keyboard.press('Escape');await page.waitForTimeout(350);assert.equal(await page.locator('body').getAttribute('data-active-page'),'radar','Late permission errors from a closed source must not clear the current result');assert.equal(await page.locator('[data-page=radar] [data-slot=evidence-list] button').count(),12);
    docDelays={};docFailures={};docURL=base+'/source-original';await context.route('**/source-original',route=>route.fulfill({contentType:'text/plain',body:'Original source'}));
    await page.locator('[data-page=radar] [data-action=open-first]').last().click();await page.waitForSelector('[data-action=original]:visible');const opened=page.waitForEvent('popup');await page.click('[data-action=original]');const popup=await opened;await popup.waitForLoadState();assert.equal(popup.url(),docURL);await popup.close();await page.keyboard.press('Escape');
    docURL='javascript:alert(1)';await page.locator('[data-page=radar] [data-action=open-first]').last().click();await page.waitForFunction(()=>document.querySelector('[data-slot=doc-access-status]').textContent==='Authorised source');assert.equal(await page.locator('[data-action=original]').isVisible(),false);
    assert.deepEqual(errors,[]);
    console.log('Browser contracts passed: real accordion visibility, 4/all event expansion, direct phone Passport with focus/Escape, stale-document refusal, inline loading/errors, clipboard/export, existing security contracts, and 13 viewport boundaries from 320 to 1600px.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
