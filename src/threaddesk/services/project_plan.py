"""Versioned plan evidence in the existing operation store; never dispatches work."""

from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from contextlib import nullcontext

from threaddesk.core.errors import ManagementError, NotFound
from threaddesk.core.models import NODE_STATUSES, now_iso
from threaddesk.core.secrets import reject_secrets
from threaddesk.services.commands.schemas import ID, obj
from threaddesk.services.commands.validation import encode, validate
from threaddesk.services.knowledge_memory import (
    knowledge_fingerprint,
    record_node,
    set_reentry,
)
from threaddesk.services.project_start import ITEM
from threaddesk.services.project_start import SCHEMA as START_SCHEMA
from threaddesk.services.thread_management import organization

GROUPS = ("goals", "next_steps", "open_questions")
KINDS = {"goals": "decision", "next_steps": "task", "open_questions": "document"}
DRAFT_STATUS = {"goals": "proposed", "next_steps": "idea", "open_questions": "waiting"}
FORMAT = "threaddesk.project-plan-revision.v1"
HEAD = "threaddesk.project-plan-head.v1"
DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
NUMBER = {"type": "integer", "minimum": 1, "maximum": 1000000}
SOURCE = {
    key: START_SCHEMA["properties"][key] for key in ("source_ref", "source_revision")
}
PLAN_SCHEMA = obj(
    {key: {"type": "array", "maxItems": 8, "items": ITEM} for key in GROUPS}, GROUPS
)
READ_SCHEMA = obj(
    {
        "project_id": ID,
        "thread_id": ID,
        "revision": NUMBER,
        "expected_plan_revision": NUMBER,
        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    },
    ("project_id", "thread_id"),
)
READ_SCHEMA["allOf"] = [
    {
        "if": {"required": ["offset"], "properties": {"offset": {"minimum": 1}}},
        "then": {"required": ["expected_plan_revision"]},
    }
]
WRITE_SCHEMA = obj(
    {
        "project_id": ID,
        "thread_id": ID,
        "expected_plan_revision": NUMBER,
        "expected_basis": DIGEST,
        "plan": PLAN_SCHEMA,
        **SOURCE,
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
            "pattern": r"\S",
        },
        "summary": {"type": "string", "maxLength": 10000},
    },
    (
        "project_id",
        "thread_id",
        "expected_plan_revision",
        "expected_basis",
        "plan",
        "source_ref",
        "source_revision",
        "reason",
    ),
)
NODE_SCHEMA = obj(
    {
        "node_id": ID,
        "node_revision": NUMBER,
        "title": ITEM,
        "status": {"enum": list(NODE_STATUSES)},
        "source_ref": {"type": "string", "maxLength": 2000},
        "source_revision": {"type": ["string", "null"], "maxLength": 256},
    },
    ("node_id", "node_revision", "title", "status", "source_ref", "source_revision"),
)
SNAPSHOT_SCHEMA = obj(
    {
        "format": {"const": FORMAT},
        "project_id": ID,
        "thread_id": ID,
        "revision": NUMBER,
        "previous_digest": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
        "recorded_at": {"type": ["string", "null"]},
        "origin": {"enum": ["created", "observed_m2", "revision"]},
        "reason": {"type": "string", "maxLength": 2000},
        **SOURCE,
        "summary": {"type": "string", "maxLength": 10000},
        "plan": obj(
            {
                key: {"type": "array", "maxItems": 8, "items": NODE_SCHEMA}
                for key in GROUPS
            },
            GROUPS,
        ),
    },
    (
        "format",
        "project_id",
        "thread_id",
        "revision",
        "previous_digest",
        "recorded_at",
        "origin",
        "reason",
        "source_ref",
        "source_revision",
        "summary",
        "plan",
    ),
)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def key(thread_id, revision):
    return "project-plan-" + digest([thread_id, revision])


def conflict(message="Project plan evidence or head is inconsistent."):
    raise ManagementError("plan_state_conflict", message)


def _validate_snapshot(value, project_id, thread_id, revision):
    try:
        validate(SNAPSHOT_SCHEMA, value)
    except ManagementError:
        conflict()
    if (value["project_id"], value["thread_id"], value["revision"]) != (
        project_id,
        thread_id,
        revision,
    ):
        conflict()
    ids = [item["node_id"] for values in value["plan"].values() for item in values]
    if len(ids) != len(set(ids)):
        conflict()
    return value


def _load(svc, project_id, thread_id, revision):
    identity = key(thread_id, revision)
    record = svc.store.get_management_operation(identity)
    if record is None:
        return None
    if (
        not isinstance(record, dict)
        or record.get("kind") != "project_plan_revision"
        or record.get("storage_operation_id") != identity
    ):
        conflict()
    value = _validate_snapshot(record.get("result"), project_id, thread_id, revision)
    if digest(value) != record.get("request_hash"):
        conflict()
    return value


def _put(svc, value):
    identity = key(value["thread_id"], value["revision"])
    if svc.store.get_management_operation(identity) is not None:
        conflict("A plan revision already exists; it will not be overwritten.")
    _validate_snapshot(
        value, value["project_id"], value["thread_id"], value["revision"]
    )
    reject_secrets(encode(value))
    svc.store.save_management_operation(
        identity,
        {
            "storage_operation_id": identity,
            "kind": "project_plan_revision",
            "request_hash": digest(value),
            "recorded_at": value["recorded_at"],
            "result": value,
        },
    )
    return {
        "format": HEAD,
        "project_id": value["project_id"],
        "thread_id": value["thread_id"],
        "revision": value["revision"],
        "digest": digest(value),
    }


def _scope(svc, project_id, thread_id):
    project, thread = svc.store.get_node(project_id), svc.store.get_thread(thread_id)
    starter = thread.context.extra.get("project_start")
    if (
        project.kind != "project"
        or organization(thread)["project_id"] != project_id
        or not isinstance(starter, dict)
        or starter.get("project_id") != project_id
    ):
        raise ManagementError(
            "scope_conflict", "Plan and thread must belong to the exact project."
        )
    if starter.get("format") != "threaddesk.project-start.v1":
        conflict("Unsupported project start format.")
    return project, thread


def _node(svc, thread, group, identity):
    node = svc.store.get_node(identity)
    if (
        node.metadata.get("thread_id") != thread.id
        or node.kind != KINDS[group]
        or (
            group == "open_questions"
            and node.metadata.get("knowledge_type") != "question"
        )
        or node.metadata.get("project_id", organization(thread)["project_id"])
        != organization(thread)["project_id"]
    ):
        raise ManagementError(
            "scope_conflict", "A plan item has incompatible ownership."
        )
    return node


def _item(node):
    value = {
        "node_id": node.id,
        "node_revision": node.revision,
        "title": node.title,
        "status": node.status,
        "source_ref": node.source,
        "source_revision": node.metadata.get("source_revision"),
    }
    try:
        validate(NODE_SCHEMA, value)
    except ManagementError:
        conflict("A referenced plan item has an unsupported shape.")
    return value


def _observed(svc, thread, project_id):
    refs = thread.context.extra["project_start"].get("initial_node_ids")
    if not isinstance(refs, dict) or set(refs) != set(GROUPS):
        conflict("An explicit ordered M2 plan is required.")
    plan = {}
    for group in GROUPS:
        if (
            not isinstance(refs[group], list)
            or len(refs[group]) > 8
            or any(not isinstance(i, str) or not ID_CHECK(i) for i in refs[group])
        ):
            conflict()
        plan[group] = [
            _item(_node(svc, thread, group, identity)) for identity in refs[group]
        ]
    saved = thread.context.extra.get("reentry", {})
    if not isinstance(saved, dict):
        conflict("Existing re-entry has an unsupported shape.")
    return _validate_snapshot(
        {
            "format": FORMAT,
            "project_id": project_id,
            "thread_id": thread.id,
            "revision": 1,
            "previous_digest": None,
            "recorded_at": None,
            "origin": "observed_m2",
            "reason": "Observed from existing M2 references; not original creation evidence.",
            "source_ref": saved.get("source_ref", "local:observed-m2-plan"),
            "source_revision": saved.get("source_revision", "unverified"),
            "summary": saved.get("summary", thread.description),
            "plan": plan,
        },
        project_id,
        thread.id,
        1,
    )


def ID_CHECK(value):
    from threaddesk.services.thread_management import ID as pattern

    return pattern.fullmatch(value) is not None


def _state(svc, project_id, thread_id):
    project, thread = _scope(svc, project_id, thread_id)
    head = thread.context.extra.get("project_plan")
    if "project_plan" not in thread.context.extra:
        if svc.store.get_management_operation(key(thread_id, 1)) is not None:
            conflict("Plan head was removed or restored; existing history is retained.")
        snapshot = _observed(svc, thread, project_id)
    else:
        try:
            validate(
                obj(
                    {
                        "format": {"const": HEAD},
                        "project_id": ID,
                        "thread_id": ID,
                        "revision": NUMBER,
                        "digest": DIGEST,
                    },
                    ("format", "project_id", "thread_id", "revision", "digest"),
                ),
                head,
            )
        except ManagementError:
            conflict()
        snapshot = _load(svc, project_id, thread_id, head["revision"])
        if (
            snapshot is None
            or head["project_id"] != project_id
            or head["thread_id"] != thread_id
            or head["digest"] != digest(snapshot)
            or svc.store.get_management_operation(key(thread_id, head["revision"] + 1))
            is not None
        ):
            conflict("Plan head differs from retained history; no automatic repair.")
        if snapshot["revision"] > 1:
            previous = _load(svc, project_id, thread_id, snapshot["revision"] - 1)
            if previous is None or digest(previous) != snapshot["previous_digest"]:
                conflict()
    live = {
        group: [
            _item(_node(svc, thread, group, item["node_id"]))
            for item in snapshot["plan"][group]
        ]
        for group in GROUPS
    }
    basis = digest(
        {
            "project": project.to_dict(),
            "thread": thread.to_dict(),
            "snapshot": digest(snapshot),
            "knowledge": knowledge_fingerprint(svc, thread_id),
        }
    )
    return thread, snapshot, live, basis


def _current(snapshot, live):
    closed = {"accepted", "done", "archived", "superseded"}
    pending = next(
        (item for item in live["next_steps"] if item["status"] not in closed), None
    )
    return {
        "plan_revision": snapshot["revision"],
        "summary": snapshot["summary"],
        "next_step": pending["title"] if pending else "",
        "next_node_id": pending["node_id"] if pending else None,
        "source_ref": snapshot["source_ref"],
        "source_revision": snapshot["source_revision"],
        "source_verification": "referenced_unverified",
        "derived_from_live_status": True,
    }


def current_context(svc, thread):
    if (
        "project_start" not in thread.context.extra
        and "project_plan" not in thread.context.extra
    ):
        return None
    try:
        project_id = organization(thread)["project_id"]
        if not isinstance(project_id, str) or not ID_CHECK(project_id):
            raise ManagementError("scope_conflict", "No exact project binding.")
        _, snapshot, live, _ = _state(svc, project_id, thread.id)
        return {"available": True, **_current(snapshot, live)}
    except (ManagementError, NotFound) as exc:
        return {"available": False, "code": getattr(exc, "code", "plan_state_conflict")}


def get(svc, arguments):
    validate(READ_SCHEMA, arguments)
    try:
        with nullcontext() if svc.store.in_transaction else svc.store.transaction():
            thread, current, live, basis = _state(
                svc, arguments["project_id"], arguments["thread_id"]
            )
            if (
                arguments.get("expected_plan_revision", current["revision"])
                != current["revision"]
            ):
                raise ManagementError(
                    "plan_basis_conflict",
                    "Plan history changed; reload its first page.",
                )
            chosen = arguments.get("revision", current["revision"])
            snapshot = (
                current
                if chosen == current["revision"]
                else _load(svc, arguments["project_id"], thread.id, chosen)
            )
            if snapshot is None or chosen > current["revision"]:
                raise ManagementError("not_found", "Plan revision was not found.")
            offset, limit = arguments.get("offset", 0), arguments.get("limit", 5)
            history = []
            for number in range(
                current["revision"] - offset,
                max(0, current["revision"] - offset - limit),
                -1,
            ):
                record = (
                    current
                    if number == current["revision"]
                    else _load(svc, arguments["project_id"], thread.id, number)
                )
                if record is None:
                    conflict()
                history.append(
                    {
                        key: record[key]
                        for key in (
                            "revision",
                            "recorded_at",
                            "origin",
                            "reason",
                            "source_ref",
                            "source_revision",
                        )
                    }
                )
            result = {
                "format": "threaddesk.project-plan.v1",
                "project_id": arguments["project_id"],
                "thread_id": thread.id,
                "thread_revision": thread.revision,
                "plan_revision": current["revision"],
                "basis_digest": basis,
                "snapshot": snapshot,
                "live_plan": live,
                "current_reentry": _current(current, live),
                "history": history,
                "total_revisions": current["revision"],
                "next_offset": offset + len(history)
                if offset + len(history) < current["revision"]
                else None,
                "execution_started": False,
                "source_verification": "referenced_unverified",
            }
            reject_secrets(encode(result))
            return result
    except NotFound as exc:
        raise ManagementError(
            "not_found", "Project plan or referenced item was not found."
        ) from exc


def initialize(svc, thread, draft):
    snapshot = _observed(
        svc, thread, thread.context.extra["project_start"]["project_id"]
    )
    snapshot.update(
        recorded_at=now_iso(),
        origin="created",
        reason="Initial saved draft.",
        source_ref=draft["source_ref"],
        source_revision=draft["source_revision"],
    )
    thread.context.extra["project_plan"] = _put(svc, snapshot)


def revise(svc, arguments):
    validate(WRITE_SCHEMA, arguments)
    reject_secrets(encode(arguments))
    if not svc.store.in_transaction:
        raise ManagementError(
            "invalid_state", "Use the transactional project.plan.revise command."
        )
    thread, current, live, basis = _state(
        svc, arguments["project_id"], arguments["thread_id"]
    )
    if thread.status == "archived":
        raise ManagementError(
            "invalid_state", "Unarchive the thread before revising its plan."
        )
    if (
        current["revision"] != arguments["expected_plan_revision"]
        or basis != arguments["expected_basis"]
    ):
        raise ManagementError(
            "plan_basis_conflict",
            "The plan or knowledge changed; reload before revising.",
        )
    if current["recorded_at"] is None:
        current = {**current, "recorded_at": now_iso()}
        _put(svc, current)
    number = current["revision"] + 1
    source = {name: arguments[name] for name in SOURCE}
    plan, retained = {}, set()
    for group in GROUPS:
        matches = defaultdict(deque)
        for item in live[group]:
            matches[item["title"]].append(item)
        plan[group] = []
        for raw in arguments["plan"][group]:
            title = raw.strip()
            if matches[title]:
                item = matches[title].popleft()
                retained.add(item["node_id"])
            else:
                node = record_node(
                    svc,
                    thread,
                    {
                        **source,
                        "kind": "question"
                        if group == "open_questions"
                        else KINDS[group],
                        "status": DRAFT_STATUS[group],
                        "title": title,
                    },
                )
                node.metadata["plan_lineage"] = {
                    "project_id": arguments["project_id"],
                    "revision": number,
                    "previous_revision": current["revision"],
                }
                svc.store.save_node(node)
                item = _item(node)
            plan[group].append(item)
    for group in GROUPS:
        for item in live[group]:
            if (
                item["node_id"] not in retained
                and item["status"] == DRAFT_STATUS[group]
            ):
                node = _node(svc, thread, group, item["node_id"])
                node.status = "superseded"
                node.revision += 1
                node.updated_at = now_iso()
                node.metadata["plan_retirement"] = {
                    **source,
                    "project_id": arguments["project_id"],
                    "revision": number,
                }
                svc.store.save_node(node)
                svc._record_graph_event(
                    "project.plan_item_retired", node.id, node.kind, node.revision
                )
    snapshot = {
        "format": FORMAT,
        "project_id": arguments["project_id"],
        "thread_id": thread.id,
        "revision": number,
        "previous_digest": digest(current),
        "recorded_at": now_iso(),
        "origin": "revision",
        "reason": arguments["reason"],
        **source,
        "summary": arguments.get("summary", current["summary"]),
        "plan": plan,
    }
    thread.context.extra["project_plan"] = _put(svc, snapshot)
    current_reentry = _current(snapshot, plan)
    set_reentry(
        thread,
        {
            **source,
            "summary": snapshot["summary"],
            "next_step": current_reentry["next_step"],
        },
    )
    thread.updated_at = now_iso()
    svc.store.save_thread(thread)
    svc.bus.emit(
        "project.plan_revised",
        {
            "project_id": arguments["project_id"],
            "thread_id": thread.id,
            "revision": number,
        },
    )
    return {
        "format": "threaddesk.project-plan-revised.v1",
        "project_id": arguments["project_id"],
        "thread_id": thread.id,
        "thread_revision": thread.revision,
        "plan_revision": number,
        "snapshot_digest": digest(snapshot),
        "execution_started": False,
    }
