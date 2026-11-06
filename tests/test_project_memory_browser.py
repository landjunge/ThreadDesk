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


@pytest.mark.parametrize("language,width", [("de", 1280), ("en", 390)])
def test_idea_preview_edit_validation_save_and_existing_selection(
    demo, language, width
):
    from threaddesk.storage.json_store import JsonStore

    store = JsonStore(Path(demo["workspace"]))
    before_id = store.get_current_id()
    before_threads = len(store.list_threads())
    before_nodes = len(store.list_nodes())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("THREADDESK_CHROMIUM") or None
        )
        try:
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page.goto(demo["url"] + "?lang=" + language)
            page.get_by_role(
                "link",
                name="Neues Projekt" if language == "de" else "New project",
                exact=True,
            ).click()
            page.wait_for_url("**/projects/new?**")
            intake = page.locator("[data-project-intake]")
            operation = intake.locator('[name="operation_id"]').input_value()
            title = "Browserstart-" + language
            intake.locator('[name="title"]').fill(title)
            intake.locator('[name="idea"]').fill(
                "Eine neue Projektidee in eigenen Worten festhalten."
            )
            intake.get_by_role("button").click()
            page.locator("[data-project-draft]").wait_for()
            assert page.locator('[name="operation_id"]').input_value() == operation
            assert (
                len(store.list_threads()) == before_threads
                and len(store.list_nodes()) == before_nodes
            )
            page.locator('[name="goals"]').fill("x" * 301)
            page.locator("[data-project-intake] button").click()
            page.locator('[role="alert"]').wait_for()
            assert page.locator('[name="operation_id"]').input_value() == operation
            assert len(store.list_threads()) == before_threads
            page.locator('[name="goals"]').fill(
                "Quellen prüfen und Ergebnis nachvollziehbar festhalten"
            )
            page.locator('[name="next_steps"]').fill(
                "Erste Quelle prüfen\nErgebnis dokumentieren"
            )
            boxes = page.locator(
                '.project-memory-shell, main, [data-project-intake], [data-project-intake] input:not([type="hidden"]), [data-project-intake] textarea, [data-project-intake] button'
            ).evaluate_all(
                "nodes => nodes.map(n => { const r=n.getBoundingClientRect(); return [r.left,r.right,r.width]; })"
            )
            assert all(
                left >= 0 and right <= width + 1 and size > 0
                for left, right, size in boxes
            ), boxes
            destination = Path(
                os.environ.get(
                    "THREADDESK_PROJECT_MEMORY_EVIDENCE", "test-results/project-memory"
                )
            )
            destination.mkdir(parents=True, exist_ok=True)
            page.locator("main").evaluate("n => n.scrollTo(0,0)")
            page.screenshot(
                path=str(destination / f"start-draft-{language}-{width}.png")
            )
            page.locator("[data-project-intake] button").click()
            page.wait_for_url(
                lambda url: "/projects?project_id=" in str(url),
                wait_until="networkidle",
            )
            assert page.locator("#project-memory-project").inner_text() == title
            assert "Erste Quelle prüfen" in page.locator("main").inner_text()
            assert store.get_current_id() == before_id
            assert len(store.list_threads()) == before_threads + 1
            assert (
                len(
                    [
                        n
                        for n in store.list_nodes()
                        if n.kind == "project" and n.title == title
                    ]
                )
                == 1
            )
            new_link = page.get_by_role(
                "link",
                name="Neues Projekt" if language == "de" else "New project",
                exact=True,
            )
            box = new_link.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1
            page.locator("main").evaluate("n => n.scrollTo(0,0)")
            page.screenshot(
                path=str(destination / f"start-saved-{language}-{width}.png")
            )
        finally:
            browser.close()
