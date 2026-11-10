"""Frame: the real game in headless Chromium against the Nova server — a whole production, start to finish."""
import pytest

pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.frame


def test_full_game_in_the_browser_with_no_firebase(server):
    base, _ = server
    outside, errors = [], []
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("request", lambda r: outside.append(r.url) if not r.url.startswith(base)
                and "fonts.g" not in r.url else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/")
        page.wait_for_selector("#welcome-screen.active, #skip-intro", timeout=15000)
        page.click("#skip-intro")
        page.click("#boot-system")
        page.wait_for_selector("#screen1.active", timeout=15000)
        page.fill("#book-name", "Dune")
        page.fill("#author-name", "Frank Herbert")
        page.click("#submit-book")
        page.wait_for_selector("#screen2.active", timeout=30000)
        assert "$" in page.inner_text("#movie-budget")
        page.click("#go-to-casting")
        page.wait_for_selector("#screen3.active", timeout=15000)
        page.fill("#actor-name-0", "Zendaya")
        page.click('.cast-button[data-index="0"]')
        page.wait_for_selector("#cast-info-0:not(:empty)", timeout=15000)
        for i in range(1, 4):
            page.check(f"#no-name-{i}")
        page.click("#make-movie")
        page.wait_for_selector("#screen4.active", timeout=60000)
        score = page.inner_text("#overall-score")
        browser.close()
    assert any(c.isdigit() for c in score), score
    assert not errors, errors
    assert not outside, f"the Nova edition reached outside: {outside}"


def test_settings_panel_changes_a_brain(server):
    base, _ = server
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(base + "/")
        page.wait_for_selector("#nova-db-badge", timeout=15000)
        pw.expect(page.locator("#nova-db-badge")).to_have_text("LOCAL", timeout=10000)
        page.locator("#nova-settings-button").dispatch_event("click")
        page.wait_for_selector('select[data-role="critics"]', timeout=20000)
        page.select_option('select[data-role="critics"]', "rules")
        page.fill('input[data-role-model="critics"]', "house")
        page.locator("#nova-settings button", has_text="[SAVE BRAINS]").click()
        pw.expect(page.locator("#nova-settings-status")).to_contain_text("SAVED", timeout=10000)
        browser.close()
    import json
    import urllib.request
    brains = json.loads(urllib.request.urlopen(base + "/api/settings").read())["brains"]
    assert brains["critics"] == {"backend": "rules", "model": "house"}
