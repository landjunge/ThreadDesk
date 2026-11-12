"""Real ThreadDesk UI with isolated synthetic data; no installed app controls."""
import pytest
from playwright.sync_api import expect
from http_ui_client import choose_language
from test_design_browser import design_browser  # noqa: F401


@pytest.mark.parametrize("width", [940, 1358])
@pytest.mark.parametrize("language", ["de", "en"])
def test_family_header_compact_columns_and_details(design_browser, width, language):
    browser, url = design_browser
    page = browser.new_page(viewport={"width":width,"height":664})
    errors=[]
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        choose_language(page, url, language)
        page.goto(url + "/", wait_until="networkidle")
        expect(page.locator('.np-appbar-button')).to_have_count(5)
        result=page.evaluate("""() => {
          const box=s=>document.querySelector(s).getBoundingClientRect();
          const header=box('.topbar'), bar=box('.np-appbar'), body=box('.shell');
          return {center:(bar.left+bar.right)/2, viewport:innerWidth,
            headerHeight:header.height, bodyHeight:body.height,
            documentWidth:document.documentElement.scrollWidth,
            buttons:[...document.querySelectorAll('.np-appbar-button')].map(e=>[e.offsetWidth,e.offsetHeight]),
            columns:['.sidebar','.desk-head','.desk-side'].map(s=>{const r=box(s);return [r.left,r.right,r.width];})};
        }""")
        assert abs(result['center']-width/2)<=1, result
        assert result['headerHeight']<=104, result
        assert result['bodyHeight']==664, result
        assert result['documentWidth']<=width, result
        assert all(v==[44,44] for v in result['buttons']), result
        assert all(left>=0 and right<=width and size>=190 for left,right,size in result['columns']), result
        for code in ['DE','EN']:
            expect(page.locator('.topbar-language button', has_text=code)).to_be_visible()
        details=page.locator('[data-disclosure="files"]')
        before=details.get_attribute('open')
        details.locator('summary').click()
        assert details.get_attribute('open') != before
        button=page.locator('[data-app-id="agent-authority"]')
        button.focus()
        expect(page.locator('#'+button.get_attribute('aria-describedby'))).to_be_visible()
        assert page.locator('.brand-thread').evaluate('e=>getComputedStyle(e).color')=='rgb(185, 156, 255)'
        assert not errors
    finally:
        page.close()


def test_native_switch_does_not_navigate_or_lose_unsaved_ui(design_browser):
    browser, url = design_browser
    page=browser.new_page(viewport={"width":940,"height":664})
    try:
        page.add_init_script("window.nativeTargets=[];window.__THREADDESK_FAMILY__={switchTarget:async target=>{nativeTargets.push(target);return 'uncertain';}}")
        page.goto(url+'/', wait_until='networkidle')
        field=page.locator('.whiteboard-form textarea').first
        field.fill('Unsaved synthetic draft')
        before=page.url
        page.locator('[data-app-id="kirabridge"]').click()
        page.wait_for_function('nativeTargets.length===1')
        assert page.url==before
        assert field.input_value()=='Unsaved synthetic draft'
        assert page.evaluate('nativeTargets')==['kirabridge']
        assert page.locator('[data-app-id="kirabridge"] .np-appbar-ring').get_attribute('data-connected')=='false'
        page.locator('[data-app-id="kirabridge"]').dispatch_event('click')
        assert page.evaluate('nativeTargets.length')==1
    finally:
        page.close()
