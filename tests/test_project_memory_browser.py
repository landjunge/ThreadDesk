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


@pytest.mark.parametrize(
    "language,width,project_index", [("de", 1280, 1), ("en", 390, 2)]
)
def test_plan_revision_old_history_and_live_resume_in_browser(
    demo, language, width, project_index
):
    from threaddesk.api.service import ThreadService
    from threaddesk.services.project_plan import get as read_plan
    from threaddesk.storage.json_store import JsonStore

    project = demo["projects"][project_index]
    backend = ThreadService(JsonStore(Path(demo["workspace"])))
    selected_before = backend.store.get_current_id()
    base = demo["url"].split("/projects")[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("THREADDESK_CHROMIUM") or None
        )
        try:
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page.goto(
                demo["url"] + "?project_id=" + project["id"] + "&lang=" + language
            )
            page.get_by_role(
                "link",
                name="Plan und Verlauf öffnen"
                if language == "de"
                else "Open plan and history",
                exact=True,
            ).click()
            page.locator("[data-project-plan]").wait_for()
            path = f"/projects/{project['id']}/plan/{project['plan_thread_id']}"
            form = page.locator("[data-project-plan]")
            operation = form.locator('[name="operation_id"]').input_value()
            form.locator('[name="next_steps"]').fill(
                "M3 first pending step\nM3 second pending step"
            )
            form.locator('[name="reason"]').fill(
                "New verified local observation; source remains referenced."
            )
            boxes = form.locator("textarea, button").evaluate_all(
                "nodes => nodes.map(n => {const r=n.getBoundingClientRect(); return [r.left,r.right];})"
            )
            assert all(left >= 0 and right <= width + 1 for left, right in boxes), boxes
            destination = Path(
                os.environ.get(
                    "THREADDESK_PROJECT_MEMORY_EVIDENCE", "test-results/project-memory"
                )
            )
            destination.mkdir(parents=True, exist_ok=True)
            page.locator("main").evaluate("n => n.scrollTo(0,0)")
            page.screenshot(path=str(destination / f"plan-edit-{language}-{width}.png"))
            form.get_by_role("button").click()
            page.wait_for_url(
                lambda url: path in str(url) and "revision=" not in str(url),
                wait_until="networkidle",
            )
            page.wait_for_function(
                "document.querySelector('[name=expected_plan_revision]')?.value === '2'"
            )
            assert page.locator('[name="operation_id"]').input_value() != operation
            old = read_plan(
                backend,
                {
                    "project_id": project["id"],
                    "thread_id": project["plan_thread_id"],
                    "revision": 1,
                },
            )
            assert (
                old["plan_revision"] == 2
                and old["snapshot"]["source_revision"] == "demo-v2"
            )
            page.goto(base + path + "?revision=1&lang=" + language)
            old_view = page.locator("[data-plan-old]")
            old_view.wait_for()
            assert "demo-v2" in old_view.inner_text()
            assert "M3 second pending step" not in old_view.inner_text()
            assert page.locator("[data-project-plan]").count() == 0
            page.locator("main").evaluate("n => n.scrollTo(0,0)")
            page.screenshot(
                path=str(destination / f"plan-history-{language}-{width}.png")
            )
            live = read_plan(
                backend,
                {"project_id": project["id"], "thread_id": project["plan_thread_id"]},
            )
            first = live["live_plan"]["next_steps"][0]["node_id"]
            for state in (
                "ready",
                "assigned",
                "in_progress",
                "delivered",
                "review",
                "accepted",
            ):
                backend.transition_node(
                    first, state, expected_revision=backend.get_node(first).revision
                )
            page.goto(
                demo["url"] + "?project_id=" + project["id"] + "&lang=" + language
            )
            summary = page.locator(".project-memory-thread")
            assert "M3 second pending step" in summary.inner_text()
            assert backend.store.get_current_id() == selected_before
            assert page.locator("main").evaluate("n => n.scrollWidth <= n.clientWidth")
            page.screenshot(
                path=str(destination / f"plan-resume-{language}-{width}.png")
            )
        finally:
            browser.close()
