"""Native forms share receipts and retain drafts after uncertain delivery."""

from html.parser import HTMLParser

import pytest
from http_ui_client import UIClient
from test_project_start import svc as project_start_fixture

from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.knowledge_memory import reentry
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.server import create_app

svc = project_start_fixture


class Intake(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.active = False
        self.field = None
        self.fields = {}
        self.action = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.active = "data-project-intake" in attrs
            if self.active:
                self.action = attrs["action"]
        if self.active and tag == "input" and "name" in attrs:
            self.fields[attrs["name"]] = attrs.get("value", "")
        if self.active and tag == "textarea":
            self.field = attrs["name"]
            self.fields[self.field] = ""

    def handle_data(self, value):
        if self.active and self.field:
            self.fields[self.field] += value

    def handle_endtag(self, tag):
        if tag == "textarea":
            self.field = None
        if tag == "form":
            self.active = False


@pytest.fixture
def client(svc, monkeypatch):
    monkeypatch.setenv("THREADDESK_HOME", str(svc.store.root))
    monkeypatch.setenv(
        "THREADDESK_STORAGE", "sqlite" if isinstance(svc.store, SQLiteStore) else "json"
    )
    with UIClient(create_app()) as value:
        yield value


def draft(client):
    form = Intake(client.get("/projects/new?lang=en&mode=expert").text)
    form.fields.update(idea="An interview series for Buschradio")
    page = client.post(form.action, data=form.fields)
    assert page.status_code == 200, page.text
    result = Intake(page.text)
    assert result.fields["operation_id"] == form.fields["operation_id"]
    return page, result


def test_preview_edited_save_replay_and_readback(client, svc, monkeypatch):
    active = svc.create("Ongoing foreign work")
    refreshes = []
    import threaddesk.services.library_refresh as refresh

    monkeypatch.setattr(
        refresh,
        "refresh_existing",
        lambda *a: refreshes.append(1) or {"status": "not_built"},
    )
    page, form = draft(client)
    assert 'lang="en"' in page.text and "Local starting outline" in page.text
    assert not svc.list_nodes() and len(svc.list()) == 1 and not refreshes
    form.fields["goals"] = "Publish a sourced interview outline"
    form.fields["next_steps"] = "Draft questions\nCheck source rights"
    form.fields["open_questions"] = "Who is the first guest?"
    saved = client.post(form.action, data=form.fields, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    assert saved.headers["X-ThreadDesk-Operation"] == form.fields["operation_id"]
    assert len(refreshes) == 1
    again = client.post(form.action, data=form.fields, follow_redirects=False)
    assert (
        again.status_code == 303
        and again.headers["location"] == saved.headers["location"]
    )
    assert len(refreshes) == 1 and len(svc.list()) == 2
    assert svc.current().id == active.id
    memory = client.get(saved.headers["location"])
    assert (
        memory.status_code == 200
        and "Publish a sourced interview outline" in memory.text
    )
    receipt = CommandApplication(svc).operation(form.fields["operation_id"])
    thread_id = receipt["result"]["thread_id"]
    assert reentry(svc, {"id": thread_id})["saved"]["next_step"] == "Draft questions"
    status = client.get(
        "/projects/start-status/" + form.fields["operation_id"], follow_redirects=False
    )
    assert status.status_code == 303


def test_uncertain_save_keeps_id_and_status_never_creates(client, svc, monkeypatch):
    _, form = draft(client)
    call = CommandApplication.call

    def lost_reply(app, req, **kwargs):
        result = call(app, req, **kwargs)
        if req["command"] == "project.start":
            raise ManagementError(
                "command_unconfirmed", "synthetic reply lost after commit"
            )
        return result

    monkeypatch.setattr(CommandApplication, "call", lost_reply)
    unknown = client.post(form.action, data=form.fields)
    assert unknown.status_code == 409
    kept = Intake(unknown.text)
    assert kept.fields["operation_id"] == form.fields["operation_id"]
    assert kept.fields["idea"] == form.fields["idea"]
    assert "outcome is still unclear" in unknown.text
    assert "Nothing has been saved" not in unknown.text
    assert len(svc.list()) == 1
    status = client.get(
        "/projects/start-status/" + form.fields["operation_id"], follow_redirects=False
    )
    assert status.status_code == 303 and len(svc.list()) == 1
    missing = client.get("/projects/start-status/no-such-operation")
    assert missing.status_code == 409 and len(svc.list()) == 1


def test_invalid_form_preserves_id_and_csrf_remains_required(client, svc):
    _, form = draft(client)
    form.fields["goals"] = "x" * 301
    invalid = client.post(form.action, data=form.fields)
    assert invalid.status_code == 400
    assert Intake(invalid.text).fields["operation_id"] == form.fields["operation_id"]
    assert Intake(invalid.text).fields["goals"] == "x" * 301
    assert not svc.list_nodes() and not svc.list()
    missing_csrf = client.post(
        form.action, data=form.fields, headers={"X-ThreadDesk-CSRF": ""}
    )
    assert missing_csrf.status_code == 403 and not svc.list()


def test_large_unicode_and_escaped_idea_never_write(client, svc):
    form = Intake(client.get("/projects/new?lang=en").text)
    form.fields["idea"] = "🌊" * 10000
    preview = client.post(form.action, data=form.fields)
    assert preview.status_code == 200
    assert Intake(preview.text).fields["idea"] == form.fields["idea"]
    form.fields["idea"] = "</textarea><script>window.injected=true</script>"
    preview = client.post(form.action, data=form.fields)
    assert preview.status_code == 200 and "<script>window.injected" not in preview.text
    assert not svc.list() and not svc.list_nodes()


def test_protected_content_is_not_reflected(client, svc):
    form = Intake(client.get("/projects/new").text)
    protected = "ghp_" + "x" * 40
    form.fields["idea"] = protected
    rejected = client.post(form.action, data=form.fields)
    assert rejected.status_code == 400 and protected not in rejected.text
    assert Intake(rejected.text).fields["operation_id"] == form.fields["operation_id"]
    assert not svc.list() and not svc.list_nodes()
