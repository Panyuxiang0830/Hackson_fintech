"""Browser checks against evaluate_chat.py --serve's isolated synthetic preview."""
import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright, expect


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:17861')
    parser.add_argument('--out', type=Path, default=Path('runtime/chat/ui'))
    args = parser.parse_args()
    base = args.url.rstrip('/')
    args.out.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 900})
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto(base, wait_until='networkidle')
        accounts = await (await page.request.get(base + '/api/demo/accounts')).json()
        people = {name: next(a for a in accounts if a['name'].startswith(name))
                  for name in ('alice', 'bob', 'outside')}

        async def select(name):
            await page.select_option('#demoidentity', people[name]['id'])
            async with page.expect_response('**/api/demo/select'):
                await page.click('#demoselect')
            await expect(page.locator('#identity')).to_contain_text(people[name]['name'])
            await expect(page.locator('#ask')).to_be_enabled(timeout=90000)

        async def ask(question):
            await page.fill('#question', question)
            async with page.expect_response('**/api/ask', timeout=90000) as pending:
                await page.click('#ask')
            response = await pending.value
            result = await response.json()
            await expect(page.locator('#ask')).to_be_enabled(timeout=90000)
            return result

        await select('alice')
        await page.click('#ask')
        assert '请先输入问题' in await page.locator('#status').inner_text()
        checks.append({'empty_question': 'blocked'})
        result = await ask('HarborLedger 是做什么的？简单说一下。')
        assert result['decision'] == 'answered', result
        assert await page.locator('#answer').inner_text() == result['answer']
        assert await page.locator('.hit').count() == len(result['evidence'])
        checks.append({'answer': result['answer'], 'provider': result['provider'],
                       'citation_ids': [e['citation_id'] for e in result['evidence']]})
        async with page.expect_response('**/api/doc?**'):
            await page.locator('.hit').first.click()
        await expect(page.locator('#reader')).to_be_visible()
        assert 'HarborLedger' in await page.locator('#reader').inner_text()
        checks.append({'original_document': 'opened'})
        await page.screenshot(path=str(args.out / 'desktop.png'), full_page=True)
        await page.set_viewport_size({'width': 390, 'height': 844})
        overflow = await page.evaluate('document.documentElement.scrollWidth > innerWidth')
        await page.screenshot(path=str(args.out / 'mobile.png'), full_page=True)
        checks.append({'mobile_overflow': overflow})
        assert not overflow
        await page.set_viewport_size({'width': 1280, 'height': 900})
        await select('outside')
        assert await page.locator('#answer').is_hidden() and await page.locator('#reader').is_hidden()
        checks.append({'identity_change': 'old answer, evidence and document cleared'})
        result = await ask('TracePay 当前每日转账上限是多少？')
        assert result['decision'] == 'insufficient' and not result['evidence']
        assert result['llm_diagnostics']['attempts'] == 0
        checks.append({'unauthorised': 'safe empty; no provider call'})
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
        await page.fill('#question', 'HarborLedger 是做什么的？简单说一下。')
        await page.click('#ask')
        await asyncio.wait_for(ready.wait(), 90)
        await page.select_option('#demoidentity', people['bob']['id'])
        await page.click('#demoselect')
        await expect(page.locator('#identity')).to_contain_text('bob')
        release.set()
        await expect(page.locator('#ask')).to_be_enabled(timeout=90000)
        assert await page.locator('#answer').is_hidden() and await page.locator('.hit').count() == 0
        checks.append({'late_answer_after_identity_change': 'ignored'})
        assert not errors, errors
        await browser.close()
    report = {'url': base, 'checks': checks, 'javascript_errors': errors}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
