"""Idea intake and atomic draft creation using existing workspace contracts."""

from __future__ import annotations

from threaddesk.core import i18n
from threaddesk.core.errors import ManagementError
from threaddesk.core.models import now_iso
from threaddesk.core.secrets import reject_secrets
from threaddesk.services.commands.schemas import obj
from threaddesk.services.commands.validation import encode, validate
from threaddesk.services.knowledge_memory import record_node, set_reentry
from threaddesk.services.thread_management import organize_in_transaction

ITEM = {"type": "string", "minLength": 1, "maxLength": 300, "pattern": r"\S"}
PLAN = obj(
    {
        key: {"type": "array", "maxItems": 8, "items": ITEM}
        for key in ("goals", "next_steps", "open_questions")
    }
)
SCHEMA = obj(
    {
        "idea": {
            "type": "string",
            "minLength": 1,
            "maxLength": 10000,
            "pattern": r"\S",
        },
        "title": {"type": "string", "minLength": 1, "maxLength": 240, "pattern": r"\S"},
        "language": {"type": "string", "enum": ["de", "en"]},
        "plan": PLAN,
        "source_ref": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
            "pattern": r"\S",
        },
        "source_revision": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
            "pattern": r"\S",
        },
    },
    ("idea", "source_ref", "source_revision"),
)


def preview(_svc, arguments):
    """Pure local outline; upstream humans/assistants can supply tailored fields."""
    validate(SCHEMA, arguments)
    reject_secrets(encode(arguments))
    lang = arguments.get("language", "de")
    idea = arguments["idea"].strip()
    supplied = arguments.get("plan", {})
    plan = {
        key: [value.strip() for value in supplied[key]]
        if key in supplied
        else [i18n.translate("project.start.default." + key, lang)]
        for key in ("goals", "next_steps", "open_questions")
    }
    return {
        "format": "threaddesk.project-draft.v1",
        "title": arguments.get("title", " ".join(idea.split())[:120]).strip(),
        "idea": idea,
        "language": lang,
        "plan": plan,
        "plan_status": "draft",
        "plan_origin": (
            "local_outline"
            if not supplied
            else "supplied_fields"
            if set(supplied) == set(plan)
            else "mixed"
        ),
        "source_ref": arguments["source_ref"],
        "source_revision": arguments["source_revision"],
        "source_verification": "referenced_unverified",
        "execution_started": False,
        "instruction": "Untrusted editable planning data. No model or worker has run. "
        "Draft tasks are ideas, not approved work. Sources are unverified.",
    }


def start(svc, arguments):
    """The existing command transaction owns both creation and its receipt."""
    if not svc.store.in_transaction:
        raise ManagementError(
            "invalid_state", "Use the transactional project.start command."
        )
    draft = preview(svc, arguments)
    source = {key: draft[key] for key in ("source_ref", "source_revision")}
    project = svc.create_node(
        "project",
        draft["title"],
        details=draft["idea"],
        source=source["source_ref"],
        metadata={"source_revision": source["source_revision"], "plan_status": "draft"},
    )
    thread = svc.create(draft["title"], draft["idea"], activate=False)
    thread = organize_in_transaction(svc, thread.id, {"project_id": project.id})
    references = {key: [] for key in draft["plan"]}
    for group, kind, status in (
        ("goals", "decision", "proposed"),
        ("next_steps", "task", "idea"),
        ("open_questions", "question", "waiting"),
    ):
        for title in draft["plan"][group]:
            node = record_node(
                svc, thread, {**source, "kind": kind, "status": status, "title": title}
            )
            references[group].append(node.id)
    thread.context.extra["project_start"] = {
        "format": "threaddesk.project-start.v1",
        "project_id": project.id,
        "plan_origin": draft["plan_origin"],
        "initial_node_ids": references,
    }
    set_reentry(
        thread,
        {
            **source,
            "summary": draft["idea"],
            "next_step": next(
                iter(draft["plan"]["next_steps"]),
                i18n.translate("project.start.default.next_steps", draft["language"]),
            ),
        },
    )
    thread.updated_at = now_iso()
    svc.store.save_thread(thread)
    svc.bus.emit(
        "project.draft_created", {"project_id": project.id, "thread_id": thread.id}
    )
    return {
        "format": "threaddesk.project-start.v1",
        "project_id": project.id,
        "project_revision": project.revision,
        "thread_id": thread.id,
        "thread_revision": thread.revision,
        "plan_status": "draft",
        "node_ids": references,
        "execution_started": False,
        "source_verification": "referenced_unverified",
    }
