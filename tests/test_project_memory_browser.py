"""Exercise the candidate project selector, pagination and responsive layout."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path_factory.mktemp("project-memory-browser") / "workspace"
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    process = subprocess.Popen(
        [
            sys.executable,
            str(root / "scripts/demo_project_memory.py"),
            "--workspace",
            str(workspace),
            "--serve",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        from selectors import EVENT_READ, DefaultSelector

        with DefaultSelector() as selector:
            selector.register(process.stdout, EVENT_READ)
            assert selector.select(timeout=20), "Demo did not report its local URL"
        report = json.loads(process.stdout.readline())
        deadline = time.monotonic() + 15
        while True:
            try:
                with urlopen(report["url"], timeout=1) as response:
                    assert response.status == 200
                break
            except OSError:
                if time.monotonic() >= deadline:
                    pytest.fail("Candidate did not become ready")
                time.sleep(0.1)
        yield report
    finally:
        process.terminate()
        process.communicate(timeout=15)


@pytest.mark.parametrize(
    "language,width,scheme", [("de", 1280, "light"), ("en", 390, "dark")]
)
def test_project_selection_pagination_and_keyboard(demo, language, width, scheme):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("THREADDESK_CHROMIUM") or None
        )
        try:
            page = browser.new_page(
                viewport={"width": width, "height": 900}, color_scheme=scheme
            )
            page.goto(demo["url"] + "?lang=" + language)
            page.locator('select[name="project_id"]').select_option(
                demo["projects"][0]["id"]
            )
            page.locator('button[type="submit"]').filter(
                has_text="Stand anzeigen" if language == "de" else "Show context"
            ).click()
            page.wait_for_load_state("networkidle")
            assert page.locator("[data-thread-id]").count() == 3
            first_ids = page.locator("[data-thread-id]").evaluate_all(
                "nodes => nodes.map(n => n.dataset.threadId)"
            )
            assert (
                page.locator("#project-memory-project").inner_text()
                == "Berlin-Buch · Demo"
            )
            assert "Interviewfragen entwerfen" not in page.locator("main").inner_text()
            rectangles = page.locator(
                ".project-memory-shell, .project-memory, .knowledge-filter, "
                'select[name="project_id"], .knowledge-filter button[type="submit"], '
                ".project-memory-thread, .project-memory-thread h2"
            ).evaluate_all(
                "nodes => nodes.map(n => {const r=n.getBoundingClientRect(); "
                "return {left:r.left,right:r.right,width:r.width}})"
            )
            assert all(
                r["width"] > 0 and r["left"] >= 0 and r["right"] <= width + 1
                for r in rectangles
            ), rectangles
            assert page.locator("main").evaluate("n => n.scrollWidth <= n.clientWidth")
            next_page = page.locator("[data-project-next]")
            destination_url = next_page.get_attribute("href")
            next_page.focus()
            page.keyboard.press("Enter")
            page.wait_for_url(destination_url, wait_until="networkidle")
            assert page.locator("[data-thread-id]").count() == 1
            assert (
                page.locator("[data-thread-id]").get_attribute("data-thread-id")
                not in first_ids
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            destination = Path(
                os.environ.get(
                    "THREADDESK_PROJECT_MEMORY_EVIDENCE", "test-results/project-memory"
                )
            )
            destination.mkdir(parents=True, exist_ok=True)
            page.locator("main").evaluate("n => n.scrollTo(0,0)")
            page.screenshot(
                path=str(destination / f"{language}-{scheme}-{width}.png"),
                full_page=True,
            )
        finally:
            browser.close()
