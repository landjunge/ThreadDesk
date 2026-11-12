"""Portable renderer sources and real browser fixture; no app/peer admission."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/threaddesk/ui/static"


def test_pure_state_contract():
    subprocess.run(["node", "--test", str(ROOT / "tests/appbar_state.test.mjs")], cwd=ROOT, check=True)


def test_approved_asset_hashes_and_no_bridge_substitute():
    manifest = json.loads((STATIC / "networkpunkt-appbar-assets.json").read_text())
    bundle = json.loads((STATIC / "networkpunkt-appbar-bundle.json").read_text())
    assert bundle["version"] == manifest["version"] == "1.2.2"
    assert manifest["blocked"] == {}
    assert [x["appId"] for x in manifest["files"]] == ["kirabridge", "threaddesk", "4allpass", "tollgate", "agent-authority"]
    for asset in manifest["files"]:
        assert hashlib.sha256((STATIC / asset["file"]).read_bytes()).hexdigest() == asset["sha256"]
    checksums = (STATIC / "networkpunkt-appbar-SHA256SUMS").read_text().splitlines()
    assert {line.split("  ", 1)[1] for line in checksums} == set(bundle["files"]) | {"networkpunkt-appbar-bundle.json"}
    for line in checksums:
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((STATIC / name).read_bytes()).hexdigest() == digest


@pytest.fixture()
def appbar():
    with sync_playwright() as play:
        installed = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        executable = os.environ.get("THREADDESK_CHROMIUM") or (str(installed) if installed.exists() else None)
        browser = play.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request):
            path = request.request.url.split(".invalid", 1)[-1]
            if path == "/":
                request.fulfill(path=str(ROOT / "tests/fixtures/appbar.html"), content_type="text/html")
            elif path.startswith("/static/") and "/" not in path[len("/static/"):]:
                file = STATIC / path[len("/static/"):]
                assert file.name.startswith(("networkpunkt", "np-appbar")) and file.is_file()
                content_type = "text/javascript" if file.suffix == ".js" else "text/css" if file.suffix == ".css" else "image/png"
                request.fulfill(path=str(file), content_type=content_type)
            else:
                request.abort()

        page.route("https://appbar-fixture.invalid/**", route)
        page.route("**/*", lambda route: route.fallback() if route.request.url.startswith("https://appbar-fixture.invalid/") else route.abort())
        page.goto("https://appbar-fixture.invalid/")
        page.wait_for_function("window.ready === true")
        try:
            yield page
            assert not errors
        finally:
            page.close()
            browser.close()


def ring(page, app="4allpass"):
    return page.locator(f'[data-app-id="{app}"] .np-appbar-ring')


def test_real_dom_states_scope_staleness_and_reconnect(appbar):
    page = appbar
    assert "Status unbekannt" in page.locator('[data-app-id="4allpass"]').get_attribute("aria-label")
    page.evaluate('check("4allpass", {vault:{userRef:"fixture-user",vaultRef:"fixture-vault",allowed:true,state:"unlocked",ttlMs:1000}})')
    assert ring(page).get_attribute("data-pulse") == "true"
    page.evaluate("advance(1000)")
    assert ring(page).get_attribute("data-connected") == "true"
    assert ring(page).get_attribute("data-pulse") == "false"
    assert "Tresorstatus unbekannt" in page.locator('[data-app-id="4allpass"]').get_attribute("aria-label")
    page.evaluate('bar.fail("4allpass", bar.begin("4allpass"), "error")')
    assert ring(page).get_attribute("data-connected") == "false"
    page.evaluate('check("4allpass")')
    assert ring(page).get_attribute("data-connected") == "true"
    page.evaluate('document.dispatchEvent(new Event("visibilitychange"))')
    assert ring(page).get_attribute("data-connected") == "false"


@pytest.mark.parametrize("locale", ["de", "en"])
def test_keyboard_tooltip_open_dedup_and_no_false_connection(appbar, locale):
    page = appbar
    page.evaluate("locale => bar.setLocale(locale)", locale)
    button = page.locator('[data-app-id="4allpass"]')
    button.focus()
    assert page.locator("#np-appbar-tip-1-4allpass").is_visible()
    page.keyboard.press("Escape")
    assert not page.locator("#np-appbar-tip-1-4allpass").is_visible()
    page.keyboard.press("Enter")
    page.keyboard.press("Space")
    button.dispatch_event("click")
    assert page.evaluate("openCalls.length") == 1
    assert button.get_attribute("aria-disabled") == "true"
    page.evaluate('resolvers[0]("opened")')
    page.wait_for_function('document.querySelector("[data-app-id=\\"4allpass\\"]").getAttribute("aria-disabled") === "false"')
    assert ring(page).get_attribute("data-connected") == "false"
    label = button.get_attribute("aria-label")
    assert ("App geöffnet, Verbindung fehlt" if locale == "de" else "App opened, connection missing") in label
    page.keyboard.press("Tab")
    assert page.locator('[data-app-id="tollgate"]').evaluate("e => e === document.activeElement")


def test_unknown_open_result_late_response_and_remount_are_safe(appbar):
    page = appbar
    page.locator('[data-app-id="threaddesk"]').click()
    page.evaluate("advance(2000)")
    page.evaluate('resolvers[0]("opened")')
    page.locator('[data-app-id="threaddesk"]').dispatch_event("click")
    assert page.evaluate("openCalls.length") == 1
    assert "Öffnung unklar" in page.locator('[data-app-id="threaddesk"]').get_attribute("aria-label")
    page.evaluate("mountAgain(); mountAgain()")
    assert page.locator(".np-appbar").count() == 1
    assert page.evaluate("activeIntervals.size") == 1
    page.evaluate("bar.destroy(); bar.destroy()")
    assert page.locator(".np-appbar").count() == 0
    assert page.evaluate("activeIntervals.size") == 0
    assert page.evaluate('bar.begin("4allpass")') is None
    assert page.evaluate('bar.receive("4allpass", {}, observation("4allpass"))') is False


def test_actual_periodic_expiry_and_failed_open_message(appbar):
    page = appbar
    page.evaluate('check("4allpass", {ttlMs:500})')
    page.evaluate("time+=500;wall+=500")
    page.wait_for_function('document.querySelector("[data-app-id=\\"4allpass\\"] .np-appbar-ring").dataset.connected === "false"')
    page.locator('[data-app-id="4allpass"]').click()
    page.evaluate('resolvers[0]("failed")')
    page.wait_for_function('document.querySelector("[data-app-id=\\"4allpass\\"]").dataset.error === "true"')
    assert "Öffnen fehlgeschlagen" in page.locator('[data-app-id="4allpass"]').get_attribute("aria-label")
    assert ring(page).get_attribute("data-connected") == "false"


def test_fast_success_double_click_still_opens_once(appbar):
    page = appbar
    page.evaluate('options.onOpen=async args=>{openCalls.push({appId:args.appId,actionId:args.actionId});return {actionId:args.actionId,outcome:"opened"};};mountAgain()')
    page.locator('[data-app-id="4allpass"]').dblclick()
    assert page.evaluate("openCalls.length") == 1
    assert ring(page).get_attribute("data-connected") == "false"


def test_partial_clock_rollback_removes_rendered_ring_and_unlock_pulse(appbar):
    page = appbar
    page.evaluate('check("4allpass", {vault:{userRef:"fixture-user",vaultRef:"fixture-vault",allowed:true,state:"unlocked",ttlMs:15000}})')
    page.evaluate("time=100;wall=114000;bar.refresh()")
    assert ring(page).get_attribute("data-pulse") == "true"
    page.evaluate("time=200;wall=101000;bar.refresh()")
    assert ring(page).get_attribute("data-connected") == "false"
    assert ring(page).get_attribute("data-pulse") == "false"


@pytest.mark.parametrize("clock_change", ["wall+=5000", "time=100;wall+=1000;bar.refresh();time=200;wall-=500"])
def test_open_clock_stall_or_rollback_stays_uncertain_until_host_recovery(appbar, clock_change):
    page = appbar
    button = page.locator('[data-app-id="4allpass"]')
    button.click()
    page.evaluate(f'{clock_change};bar.refresh();resolvers[0]("opened")')
    page.wait_for_function('document.querySelector("[data-app-id=\\"4allpass\\"]").getAttribute("aria-label").includes("Öffnung unklar")', timeout=1000)
    page.evaluate("advance(700)")
    button.dispatch_event("click")
    assert page.evaluate("openCalls.length") == 1
    assert button.get_attribute("aria-disabled") == "true"
    page.evaluate('bar.clearOpen("4allpass")')
    page.evaluate("advance(600)")
    button.click()
    assert page.evaluate("openCalls.length") == 2
    page.evaluate('resolvers[1]("focused")')
    page.wait_for_function('document.querySelector("[data-app-id=\\"4allpass\\"]").getAttribute("aria-disabled") === "false"')


def test_success_cooldown_clock_rollback_needs_host_recovery_and_new_full_cooldown(appbar):
    page = appbar
    page.evaluate('options.onOpen=async args=>{openCalls.push({appId:args.appId,actionId:args.actionId});return {actionId:args.actionId,outcome:"opened"};};mountAgain()')
    button = page.locator('[data-app-id="4allpass"]')
    button.click()
    page.wait_for_function('document.querySelector("[data-app-id=\\"4allpass\\"]").getAttribute("aria-disabled") === "false"')
    page.evaluate("time=100;wall=99900;bar.refresh()")
    button.dispatch_event("click")
    assert page.evaluate("openCalls.length") == 1
    assert "Öffnung unklar" in button.get_attribute("aria-label")
    page.evaluate("advance(10000)")
    button.dispatch_event("click")
    assert page.evaluate("openCalls.length") == 1
    page.evaluate('bar.clearOpen("4allpass");advance(599)')
    button.dispatch_event("click")
    assert page.evaluate("openCalls.length") == 1
    page.evaluate("advance(1)")
    button.click()
    assert page.evaluate("openCalls.length") == 2


def test_catalog_colors_are_available_without_host_overrides(appbar):
    page = appbar
    page.evaluate('options.colors={};mountAgain();check("4allpass", {vault:{userRef:"fixture-user",vaultRef:"fixture-vault",allowed:true,state:"unlocked",ttlMs:1000}})')
    assert ring(page).get_attribute("data-connected") == "true"
    assert ring(page).get_attribute("data-pulse") == "true"


@pytest.mark.parametrize("width", [1440, 320])
def test_fixed_icon_geometry_and_only_ring_motion(appbar, width):
    page = appbar
    page.set_viewport_size({"width": width, "height": 760})
    before = page.locator(".np-appbar-button").evaluate_all("es => es.map(e => {const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})")
    page.evaluate('check("4allpass", {vault:{userRef:"fixture-user",vaultRef:"fixture-vault",allowed:true,state:"unlocked",ttlMs:15000}})')
    after = page.locator(".np-appbar-button").evaluate_all("es => es.map(e => {const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})")
    assert before == after
    assert all(r[2:] == [44, 44] and r[0] >= 0 and r[0] + r[2] <= width for r in after)
    assert after[1][0] - after[0][0] == 48
    art = page.locator('.np-appbar-art').evaluate_all('es=>es.map(e=>{const r=e.getBoundingClientRect();return Math.max(r.width,r.height);})')
    assert all(abs(size - 32) < 0.1 for size in art), art
    assert ring(page).evaluate('e => getComputedStyle(e,"::before").animationDuration') == "12s"
    assert ring(page).locator("img").evaluate("e => getComputedStyle(e).opacity") == "1"
    page.emulate_media(reduced_motion="reduce")
    assert ring(page).evaluate('e => getComputedStyle(e,"::before").animationName') == "none"
    assert "Tresor entsperrt" in page.locator('[data-app-id="4allpass"]').get_attribute("aria-label")
    for locale in ["de", "en"]:
        page.evaluate("locale => bar.setLocale(locale)", locale)
        for app in ["threaddesk", "4allpass"]:
            button = page.locator(f'[data-app-id="{app}"]')
            button.focus()
            box = page.locator(f'#{button.get_attribute("aria-describedby")}').bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
    page.set_viewport_size({"width": 320, "height": 760})
    page.wait_for_function("""id => {
        const box = document.getElementById(id).getBoundingClientRect();
        return box.left >= 0 && box.right <= 320;
    }""", arg=button.get_attribute("aria-describedby"))
    box = page.locator(f'#{button.get_attribute("aria-describedby")}').bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 320


def test_host_native_hook_only_receives_catalog_id_and_never_connects_peer(appbar):
    page = appbar
    page.evaluate("""async () => {
      bar.destroy(); const {mountProductHeader}=await import('/static/networkpunkt-product-header.js');
      window.nativeIds=[];
      window.host=mountProductHeader(document.querySelector('#slot'), {selfId:'threaddesk',
        openTarget:async id=>{nativeIds.push(id);return 'focused';},
        navigate:()=>{throw Error('Native switch must not navigate');}});
    }""")
    page.locator('[data-app-id="kirabridge"]').click()
    page.wait_for_function("nativeIds.length === 1")
    assert page.evaluate("nativeIds") == ["kirabridge"]
    assert ring(page, "kirabridge").get_attribute("data-connected") == "false"
    page.evaluate("host.destroy()")


@pytest.mark.parametrize("elapsed_ms", [2500, 30000])
def test_native_receipt_after_two_seconds_allows_a_new_user_switch(appbar, elapsed_ms):
    page = appbar
    page.clock.install()
    page.evaluate("""async () => {
      bar.destroy(); const {mountProductHeader}=await import('/static/networkpunkt-product-header.js');
      window.nativeIds=[]; window.nativeReplies=[];
      window.host=mountProductHeader(document.querySelector('#slot'), {selfId:'threaddesk',
        openTarget:id=>{nativeIds.push(id);return new Promise(resolve=>nativeReplies.push(resolve));},
        navigate:()=>{throw Error('Native switch must not navigate');}});
    }""")
    button = page.locator('[data-app-id="kirabridge"]')
    button.click()
    page.clock.fast_forward(elapsed_ms)
    button.dispatch_event("click")
    assert page.evaluate("nativeIds") == ["kirabridge"]
    assert button.get_attribute("aria-disabled") == "true"
    page.evaluate("nativeReplies[0]('focused')")
    expect = 'document.querySelector("[data-app-id=kirabridge]").getAttribute("aria-disabled") === "false"'
    page.wait_for_function(expect, timeout=1000)
    assert ring(page, "kirabridge").get_attribute("data-connected") == "false"
    assert page.evaluate("nativeIds") == ["kirabridge"]
    # Only this subsequent explicit user action starts the second broker turn.
    button.click()
    assert page.evaluate("nativeIds") == ["kirabridge", "kirabridge"]
    page.evaluate("nativeReplies[1]('focused')")
    page.wait_for_function(expect, timeout=1000)
    page.evaluate("host.destroy()")


@pytest.mark.parametrize("outcome", ["uncertain", "late-focused"])
def test_native_unknown_or_expired_attempt_never_replays(appbar, outcome):
    page = appbar
    page.clock.install()
    page.evaluate("""async () => {
      bar.destroy(); const {mountProductHeader}=await import('/static/networkpunkt-product-header.js');
      window.nativeIds=[];
      window.host=mountProductHeader(document.querySelector('#slot'), {selfId:'threaddesk',
        openTarget:id=>{nativeIds.push(id);return new Promise(resolve=>window.nativeReply=resolve);}});
    }""")
    button = page.locator('[data-app-id="kirabridge"]')
    button.click()
    if outcome == "uncertain":
        page.evaluate("nativeReply('uncertain')")
    page.clock.fast_forward(31000)
    if outcome == "late-focused":
        page.evaluate("nativeReply('focused')")
    page.clock.fast_forward(1000)
    button.dispatch_event("click")
    assert button.get_attribute("aria-disabled") == "true"
    assert page.evaluate("nativeIds") == ["kirabridge"]
    page.evaluate("host.destroy()")


def test_delayed_dialog_close_does_not_steal_new_keyboard_focus(appbar):
    page = appbar
    page.evaluate("""async () => {
      bar.destroy(); const {mountProductHeader}=await import('/static/networkpunkt-product-header.js');
      window.host=mountProductHeader(document.querySelector('#slot'), {selfId:'threaddesk'});
    }""")
    page.locator('[data-app-id="kirabridge"]').click()
    assert page.locator('dialog').is_visible()
    page.evaluate("""() => {
      const dialog=document.querySelector('dialog'); dialog.close();
      document.querySelector('#after').focus(); dialog.dispatchEvent(new Event('close'));
    }""")
    assert page.locator('#after').evaluate('e=>e===document.activeElement')
    page.evaluate("host.destroy()")
