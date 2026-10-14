"""Browser checks against evaluate_chat.py --serve's isolated synthetic preview."""
import argparse
import asyncio
import json
from pathlib import Path


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:17861')
    parser.add_argument('--out', type=Path, default=Path('runtime/chat/ui'))
    args = parser.parse_args()
    from playwright.async_api import async_playwright, expect
    base = args.url.rstrip('/')
    args.out.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 900})
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto(base, wait_until='networkidle')
        if await page.locator('body').get_attribute('data-demo-auto-entry') == 'true':
            await expect(page.locator('#query-input')).to_be_enabled(timeout=90000)
            await expect(page.locator('#current-identity')).to_contain_text('alice')
            assert 'HarborLedger' in await page.locator('#query-input').input_value()
            checks.append({'fresh_browser': 'employee selected and question enabled without manual login'})
        accounts = await (await page.request.get(base + '/api/demo/accounts')).json()
        people = {name: next(a for a in accounts if a['name'].startswith(name))
                  for name in ('alice', 'bob', 'outside', 'ContextLedger 管理员')}

        async def select(name):
            async with page.expect_response('**/api/demo/select'):
                await page.select_option('#demo-account-select', people[name]['id'])
            await expect(page.locator('#current-identity')).to_contain_text(people[name]['name'])
            await expect(page.locator('#btn-ask')).to_be_enabled(timeout=90000)

        async def ask(question):
            await page.fill('#query-input', question)
            async with page.expect_response('**/api/ask', timeout=90000) as pending:
                await page.click('#btn-ask')
            response = await pending.value
            result = await response.json()
            await expect(page.locator('#btn-ask')).to_be_enabled(timeout=90000)
            return result

        await select('alice')
        await page.fill('#query-input', '')
        await page.click('#btn-ask')
        assert 'enter a question' in await page.locator('#error-message').inner_text()
        checks.append({'empty_question': 'blocked'})

        async def missing_csrf(route):
            headers = await route.request.all_headers()
            headers.pop('x-csrf-token', None)
            await route.continue_(headers=headers)

        await page.route('**/api/ask', missing_csrf)
        denied = await ask('TracePay 当前每日转账上限是多少？')
        assert denied['error'] == 'csrf_failed'
        await expect(page.locator('#error-state')).to_be_visible()
        await expect(page.locator('#error-message')).to_contain_text('Access denied')
        checks.append({'real_csrf_rejection': 'HTTP 403 displayed; controls recovered'})
        await page.unroute('**/api/ask', missing_csrf)

        for status, message in [(409, 'permissions changed'), (503, 'unavailable')]:
            async def fail(route):
                await route.fulfill(status=status, json={'error': 'injected_failure'})
            await page.route('**/api/ask', fail)
            await ask('TracePay 当前每日转账上限是多少？')
            await expect(page.locator('#error-state')).to_be_visible()
            await expect(page.locator('#error-message')).to_contain_text(message)
            checks.append({'injected_http_error': status, 'displayed': True})
            await page.unroute('**/api/ask', fail)

        async def disconnect(route):
            await route.abort('failed')

        await page.route('**/api/ask', disconnect)
        await page.fill('#query-input', 'TracePay 当前每日转账上限是多少？')
        await page.click('#btn-ask')
        await expect(page.locator('#error-message')).to_contain_text('connectivity error')
        await expect(page.locator('#btn-ask')).to_be_enabled()
        checks.append({'injected_network_failure': 'displayed; controls recovered'})
        await page.unroute('**/api/ask', disconnect)

        result = await ask('HarborLedger 是做什么的？简单说一下。')
        assert result['decision'] == 'answered', result
        assert await page.locator('#answer-box').inner_text() == result['answer']
        assert await page.locator('.evidence-card').count() == len(result['evidence'])
        checks.append({'answer': result['answer'], 'provider': result['provider'],
                       'citation_ids': [e['citation_id'] for e in result['evidence']]})
        async with page.expect_response('**/api/doc?**'):
            await page.locator('.evidence-card').first.click()
        await expect(page.locator('#document-reader')).to_be_visible()
        assert 'HarborLedger' in await page.locator('#document-reader').inner_text()
        checks.append({'original_document': 'opened'})
        await page.screenshot(path=str(args.out / 'desktop.png'), full_page=True)
        await page.click('#btn-close-doc')
        await page.fill('#query-input', 'HarborLedger: a changed question')
        assert await page.locator('#answer-box').is_hidden()
        assert await page.locator('.evidence-card').count() == 0
        checks.append({'question_edit': 'old results cleared'})

        await page.set_viewport_size({'width': 390, 'height': 844})
        overflow = await page.evaluate('document.documentElement.scrollWidth > innerWidth')
        await page.screenshot(path=str(args.out / 'mobile.png'), full_page=True)
        checks.append({'mobile_overflow': overflow})
        assert not overflow
        await page.set_viewport_size({'width': 1280, 'height': 900})
        await select('outside')
        assert await page.locator('#answer-box').is_hidden() and await page.locator('#document-reader').is_hidden()
        checks.append({'identity_change': 'old answer, evidence and document cleared'})
        result = await ask('TracePay 当前每日转账上限是多少？')
        assert result['decision'] == 'insufficient' and not result['evidence']
        assert result['llm_diagnostics']['attempts'] == 0
        checks.append({'unauthorised': 'safe empty; no provider call'})
        await page.reload(wait_until='networkidle')
        await expect(page.locator('#current-identity')).to_contain_text('outside')
        checks.append({'reload': 'existing selected identity preserved'})
        await select('alice')
        result = await ask('MissingOrbit721 的当前上限是多少？')
        assert result['decision'] == 'insufficient' and not result['evidence']
        checks.append({'unknown_entity': 'safe empty'})

        ready, release = asyncio.Event(), asyncio.Event()
        async def delay(route):
            response = await route.fetch(timeout=90000)
            ready.set()
            await release.wait()
            await route.fulfill(response=response)
        await page.route('**/api/ask', delay)
        await page.fill('#query-input', 'HarborLedger 是做什么的？简单说一下。')
        await page.click('#btn-ask')
        await asyncio.wait_for(ready.wait(), 90)
        await page.select_option('#demo-account-select', people['bob']['id'])
        await expect(page.locator('#current-identity')).to_contain_text('bob')
        release.set()
        await expect(page.locator('#btn-ask')).to_be_enabled(timeout=90000)
        assert await page.locator('#answer-box').is_hidden() and await page.locator('.evidence-card').count() == 0
        checks.append({'late_answer_after_identity_change': 'ignored'})
        await page.unroute('**/api/ask', delay)

        error_ready, error_release = asyncio.Event(), asyncio.Event()
        async def late_error(route):
            error_ready.set()
            await error_release.wait()
            await route.fulfill(status=409, json={'error': 'injected_old_conflict'})
        await page.route('**/api/ask', late_error)
        await page.fill('#query-input', 'HarborLedger 是做什么的？')
        await page.click('#btn-ask')
        await asyncio.wait_for(error_ready.wait(), 10)
        await page.select_option('#demo-account-select', people['alice']['id'])
        await expect(page.locator('#current-identity')).to_contain_text('alice')
        current_generation = await page.evaluate('requestGeneration')
        error_release.set()
        await expect(page.locator('#btn-ask')).to_be_enabled(timeout=90000)
        assert await page.evaluate('requestGeneration') == current_generation
        await expect(page.locator('#onboarding-state')).to_be_visible()
        assert await page.locator('#error-state').is_hidden()
        checks.append({'injected_late_error_after_identity_change': 'ignored'})
        await page.unroute('**/api/ask', late_error)

        await select('ContextLedger 管理员')
        await page.click('#nav-admin')
        await expect(page.locator('#view-admin')).to_be_visible()
        await expect(page.locator('#admin-user-id option')).to_have_count(len(accounts) + 1)
        await page.click('#btn-load-users')
        await expect(page.locator('#admin-users-list')).to_contain_text('alice')
        checks.append({'admin_navigation': 'users and permission controls available'})
        await page.click('#nav-audit')
        async with page.expect_response('**/api/audit?**'):
            await page.click('#audit-search')
        await expect(page.locator('#audit-results')).to_contain_text('Audit chain verified')
        await expect(page.locator('#audit-export')).to_be_enabled()
        checks.append({'audit_navigation': 'redacted events and export available'})
        await select('alice')
        await expect(page.locator('#view-workspace')).to_be_visible()
        assert not errors, errors
        await browser.close()
    report = {'url': base, 'checks': checks, 'javascript_errors': errors}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
