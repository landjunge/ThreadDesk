"""Plan forms keep bases/drafts on conflicts and read receipts after UNKNOWN."""

import re

from test_project_plan import get, seed
from test_project_plan import svc as project_fixture
from test_project_start import create
from test_project_start_ui import Intake
from test_project_start_ui import client as ui_fixture

from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication

svc = project_fixture
client = ui_fixture


def url(started):
    return f"/projects/{started['project_id']}/plan/{started['thread_id']}"


def edit(client, started):
    page = client.get(url(started) + "?lang=en&mode=expert")
    assert page.status_code == 200, page.text
    form = Intake(page.text)
    assert form.fields["expected_plan_revision"] == "1"
    form.fields.update(
        next_steps="Second\nThird", reason="New source changes the plan."
    )
    return form


def test_edit_replay_history_and_current_reentry(client, svc):
    active = svc.create("Other selected work")
    started = seed(svc)
    form = edit(client, started)
    saved = client.post(form.action, data=form.fields, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    assert saved.headers["X-ThreadDesk-Operation"] == form.fields["operation_id"]
    replay = client.post(form.action, data=form.fields, follow_redirects=False)
    assert replay.status_code == 303
    assert get(svc, started)["plan_revision"] == 2 and svc.current().id == active.id
    old = client.get(url(started) + "?lang=en&revision=1")
    assert old.status_code == 200 and "data-project-plan" not in old.text
    fragment = re.search(
        r"<section[^>]*data-plan-old>(.*?)</section>", old.text, re.DOTALL
    )[1]
    assert "First" in fragment and "Third" not in fragment
    current = client.get(saved.headers["location"])
    assert "Current resume context" in current.text and "Second" in current.text
    memory = client.get(
        "/projects", params={"project_id": started["project_id"], "lang": "en"}
    )
    assert "Open plan and history" in memory.text


def test_live_knowledge_conflict_preserves_original_form_basis(client, svc):
    started = seed(svc)
    form = edit(client, started)
    step = get(svc, started)["live_plan"]["next_steps"][0]
    svc.transition_node(
        step["node_id"], "ready", expected_revision=step["node_revision"]
    )
    conflict = client.post(form.action, data=form.fields)
    assert conflict.status_code == 409
    assert "knowledge or project membership changed" in conflict.text
    kept = Intake(conflict.text)
    for key in (
        "operation_id",
        "expected_revision",
        "expected_plan_revision",
        "expected_basis",
        "next_steps",
        "reason",
    ):
        assert kept.fields[key] == form.fields[key]
    assert get(svc, started)["plan_revision"] == 1


def test_lost_reply_keeps_draft_and_status_read_does_not_repeat(
    client, svc, monkeypatch
):
    started = seed(svc)
    form = edit(client, started)
    call = CommandApplication.call

    def lost(app, req, **kw):
        result = call(app, req, **kw)
        if req["command"] == "project.plan.revise":
            raise ManagementError("command_unconfirmed", "synthetic loss after commit")
        return result

    monkeypatch.setattr(CommandApplication, "call", lost)
    unknown = client.post(form.action, data=form.fields)
    assert unknown.status_code == 409 and "outcome is unclear" in unknown.text
    kept = Intake(unknown.text)
    assert kept.fields["operation_id"] == form.fields["operation_id"]
    assert kept.fields["next_steps"] == form.fields["next_steps"]
    check = client.get(
        url(started) + "/operation/" + form.fields["operation_id"],
        follow_redirects=False,
    )
    assert check.status_code == 303 and get(svc, started)["plan_revision"] == 2
    other = seed(svc, "other")
    mismatched = client.get(
        url(other) + "/operation/" + form.fields["operation_id"], follow_redirects=False
    )
    assert mismatched.status_code == 409
    assert get(svc, started)["plan_revision"] == 2


def test_invalid_or_unprotected_write_cannot_create_revision(client, svc):
    started = seed(svc)
    form = edit(client, started)
    missing = client.post(
        form.action, data=form.fields, headers={"X-ThreadDesk-CSRF": ""}
    )
    assert missing.status_code == 403
    invalid = client.post(form.action, data={**form.fields, "execute": "yes"})
    assert invalid.status_code == 400
    assert get(svc, started)["plan_revision"] == 1
    protected = "ghp_" + "x" * 40
    rejected = client.post(form.action, data={**form.fields, "reason": protected})
    assert rejected.status_code == 400 and protected not in rejected.text
    assert Intake(rejected.text).fields["operation_id"] == form.fields["operation_id"]


def test_schema_maximum_unicode_plan_renders_as_one_bounded_html_view(client, svc):
    started = create(
        svc,
        operation="large-ui",
        source_ref="source:" + "🌊" * 1000,
        plan={
            key: ["🌊" * 300] * 8 for key in ("goals", "next_steps", "open_questions")
        },
    )["result"]
    page = client.get(url(started) + "?lang=en")
    assert page.status_code == 200
    assert len(Intake(page.text).fields["next_steps"].splitlines()) == 8


def test_selected_old_version_shows_its_own_source_beyond_history_page(client, svc):
    from test_project_plan import request_for

    started = seed(svc)
    app = CommandApplication(svc)
    for number in range(2, 8):
        app.call(request_for(svc, started, operation=f"ui-history-{number}"))
    page = client.get(url(started) + "?lang=en&revision=1")
    assert page.status_code == 200
    fragment = re.search(
        r"<section[^>]*data-plan-old>(.*?)</section>", page.text, re.DOTALL
    )[1]
    assert "synthetic:conversation:idea" in fragment and "message-42" in fragment
    assert "Initial saved draft." in fragment and "Ein Buch" in fragment
