"""Check the five-corpus Part A demo, including delayed identity responses."""

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path

from playwright.async_api import async_playwright


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:7860")
    parser.add_argument("--out", type=Path, default=Path("runtime/part_a"))
    args = parser.parse_args()
    base = args.url.rstrip("/")
    evidence = args.out / "ui-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(base, wait_until="networkidle")
        await page.wait_for_function("document.querySelector('#status').textContent !== 'Searching…' && document.querySelectorAll('.hit').length > 0")
        presets = await page.evaluate("Object.values(presets)")
        options = await page.locator("#corpus option").count()
        assert options == 5, options
        for preset in presets:
            async with page.expect_response("**/api/search?**") as pending:
                await page.locator(f"[data-preset='{preset['id']}']").click()
            response = await pending.value
            result = await response.json()
            await page.wait_for_function("document.querySelector('#status').textContent !== 'Searching…'")
            assert response.ok and not result.get("error"), (preset, result)
            assert "withheld" not in result and "scanned" not in result
            if preset["id"].endswith("-outside") or preset["id"] == "jordan-out":
                assert not result["hits"], (preset, result)
            else:
                assert result["hits"], preset
                expected = next((s for s in ("google_drive", "jira", "slack") if preset["id"].endswith("-" + s)), None)
                if expected:
                    assert any(h["source"] == expected for h in result["hits"]), (preset, result)
                async with page.expect_response("**/api/doc?**") as pending_doc:
                    await page.locator(".hit").first.click()
                opened = await pending_doc.value
                assert opened.ok
                await page.wait_for_function("!document.querySelector('#reader').hidden")
                assert await page.locator("#reader").inner_text()
                if preset["corpus"].startswith(("privacy_", "publicjira_")):
                    assert await page.locator("#reader a").count() == 1
            checks.append({"preset": preset["id"], "hits": len(result["hits"])})

        connection = sqlite3.connect(args.out / "canonical.sqlite")
        connection.row_factory = sqlite3.Row
        native = connection.execute("SELECT corpus,doc_id,title,text,acl_json,extra_json FROM documents WHERE corpus LIKE 'privacy_%' AND source='google_drive' ORDER BY corpus,doc_id").fetchall()
        seen = set()
        for doc in native:
            info = json.loads(doc["extra_json"])
            kind = (doc["corpus"], info["mime_type"])
            if kind in seen:
                continue
            seen.add(kind)
            principal = json.loads(doc["acl_json"])[0]
            response = await page.request.get(base + "/api/doc", params={"corpus": doc["corpus"], "principal": principal, "doc_id": doc["doc_id"]})
            payload = await response.json()
            assert response.ok and payload["doc"]["text"] == doc["text"]
            assert payload["doc"]["metadata"]["binary_sha256"] == info["binary_sha256"]
            search = await page.request.get(base + "/api/search", params={"corpus": doc["corpus"], "principal": principal, "q": doc["title"], "mode": "keyword"})
            hits = (await search.json())["hits"]
            assert any(hit["doc_id"] == doc["doc_id"] for hit in hits), (doc["title"], hits)
            checks.append({"native_file": doc["title"], "corpus": doc["corpus"]})
        assert len(seen) == 8
        for corpus in ("privacy_camille_nike", "privacy_grace_deere_company"):
            for mode in ("keyword", "vector", "hybrid"):
                response = await page.request.get(base + "/api/search", params={"corpus": corpus, "principal": corpus + ":outside", "q": "project", "mode": mode})
                payload = await response.json()
                assert response.ok and payload == {"mode": mode, "hits": []}, payload
            doc_id = connection.execute("SELECT doc_id FROM documents WHERE corpus=? LIMIT 1", (corpus,)).fetchone()[0]
            denied = await page.request.get(base + "/api/doc", params={"corpus": corpus, "principal": corpus + ":outside", "doc_id": doc_id})
            missing = await page.request.get(base + "/api/doc", params={"corpus": corpus, "principal": corpus + ":outside", "doc_id": "nonexistent"})
            assert denied.status == missing.status == 404
            assert await denied.json() == await missing.json()
            other = "privacy_grace_deere_company" if corpus == "privacy_camille_nike" else "privacy_camille_nike"
            cross = await page.request.get(base + "/api/search", params={"corpus": corpus, "principal": other + ":outside", "q": "project", "mode": "hybrid"})
            assert not (await cross.json())["hits"]
            checks.append({"acl_negative": corpus, "modes": 3, "direct_open": "404", "cross_corpus": "denied"})
        connection.close()
        jordan = await page.request.get(base + "/api/search", params={"corpus": "orgforge", "principal": "orgforge:Jordan", "q": "incident", "mode": "hybrid"})
        assert not (await jordan.json())["hits"]
        invalid = await page.request.get(base + "/api/search", params={"corpus": "orgforge", "as_of": "invalid"})
        assert invalid.status == 400
        checks.append({"omitted_day": "employment enforced", "invalid_day": 400})

        async def show_jax():
            async with page.expect_response("**/api/search?**"):
                await page.locator("[data-preset='jax-titandb']").click()
            await page.wait_for_function("document.querySelectorAll('.hit').length > 0")
            async with page.expect_response("**/api/doc?**"):
                await page.locator(".hit").first.click()
            await page.wait_for_function("!document.querySelector('#reader').hidden")

        await show_jax()
        await page.select_option("#principal", "orgforge:Dave")
        assert await page.locator(".hit").count() == 0
        assert await page.locator("#reader").is_hidden()
        assert await page.locator("#reader").inner_text() == ""
        checks.append({"principal_change": "clears results and document"})

        await show_jax()
        await page.locator("#asof").evaluate("element => {element.value = 8; element.dispatchEvent(new Event('input', {bubbles:true}));}")
        assert await page.locator(".hit").count() == 0 and await page.locator("#reader").is_hidden()
        checks.append({"day_change": "clears results and document"})

        await show_jax()
        await page.select_option("#corpus", "privacy_camille_nike")
        assert await page.locator(".hit").count() == 0 and await page.locator("#reader").is_hidden()
        await page.wait_for_function("document.querySelector('#principal').value.startsWith('privacy_camille_nike:')")
        checks.append({"corpus_change": "clears results and document"})

        await show_jax()
        ready = asyncio.Event()
        async def delayed_search(route):
            response = await route.fetch()
            ready.set()
            await asyncio.sleep(0.8)
            await route.fulfill(response=response)
        await page.route("**/api/search?**", delayed_search)
        await page.locator("#go").click()
        await asyncio.wait_for(ready.wait(), 10)
        await page.select_option("#principal", "orgforge:Dave")
        await page.wait_for_timeout(1100)
        assert await page.locator(".hit").count() == 0
        assert await page.locator("#reader").is_hidden()
        await page.unroute("**/api/search?**", delayed_search)
        checks.append({"late_search_response": "ignored after identity change"})

        await show_jax()
        ready = asyncio.Event()
        async def delayed_doc(route):
            response = await route.fetch()
            ready.set()
            await asyncio.sleep(0.8)
            await route.fulfill(response=response)
        await page.route("**/api/doc?**", delayed_doc)
        await page.locator(".hit").first.click()
        await asyncio.wait_for(ready.wait(), 10)
        await page.select_option("#principal", "orgforge:Dave")
        await page.wait_for_timeout(1100)
        assert await page.locator(".hit").count() == 0 and await page.locator("#reader").is_hidden()
        assert await page.locator("#reader").inner_text() == ""
        await page.unroute("**/api/doc?**", delayed_doc)
        checks.append({"late_document_response": "ignored after identity change"})

        async with page.expect_response("**/api/search?**"):
            await page.locator("[data-preset='publicjira_jira-jira']").click()
        await page.wait_for_function("document.querySelectorAll('.hit').length > 0")
        async with page.expect_response("**/api/doc?**"):
            await page.locator(".hit").first.click()
        await page.wait_for_function("!document.querySelector('#reader').hidden")
        reader = await page.locator("#reader").inner_text()
        assert all(label in reader for label in ("Updated:", "Project:", "Status:", "Comments:", "Changes:")), reader
        await page.screenshot(path=str(evidence / "desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        overflow = await page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        assert not overflow
        await page.screenshot(path=str(evidence / "mobile.png"), full_page=True)
        checks.append({"jira_fields": "shown", "mobile_overflow": False})
        assert not errors, errors
        await browser.close()
    report = {"ok": True, "url": base, "checks": checks, "javascript_errors": errors}
    (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


asyncio.run(main())
