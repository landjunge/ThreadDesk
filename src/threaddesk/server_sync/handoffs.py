"""Opt-in project-bound handoff transport. Never executes agents."""

from __future__ import annotations

import hashlib
import json
import re

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from threaddesk.core.errors import ManagementError
from threaddesk.services.issued_handoffs import IssuedHandoffs
from threaddesk.services.mcp import McpBridge

FORMAT = "threaddesk.handoff-http.v1"
TOOLS = frozenset(
    {
        "issue_handoff",
        "get_issued_handoff",
        "bind_handoff_run",
        "record_handoff_question",
        "answer_handoff_question",
        "import_return",
        "get_return",
        "review_return",
        "reserve_handoff_delivery",
    }
)
INTERACTIVE = frozenset({"answer_handoff_question", "review_return"})


def subject_ref(user: str, project_id: str) -> str:
    value = json.dumps(
        [FORMAT, user, project_id], separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _same_project(thread_id, project_id):
    if thread_id != project_id:
        raise HTTPException(404, "Handoff source not found in this project")


def _issued(core, project_id, **reference):
    value = core.get_issued_handoff(**reference)
    if value.get("found"):
        _same_project(value["issued"]["handoff"]["thread_id"], project_id)
    return value


def _returned(core, project_id, return_id):
    value = core.get_return(return_id)
    if value.get("found"):
        _same_project(value["item"]["return"]["thread_id"], project_id)
    return value


def reserve_delivery(core, project_id, arguments):
    """Immutable receipt in the existing issued record, not an execution queue."""
    fields = {
        "handoff_id",
        "core_task_id",
        "device_ref",
        "operator_scope",
        "principal_ref",
        "request_sha256",
        "envelope_sha256",
    }
    if set(arguments) != fields:
        raise HTTPException(400, "Exact delivery binding required")
    for key, value in arguments.items():
        pattern = (
            r"[a-f0-9]{64}"
            if key.endswith("sha256") or key in {"operator_scope", "principal_ref"}
            else r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
        )
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise HTTPException(400, "Invalid delivery binding")
    with core.store.transaction():
        record = IssuedHandoffs(core).get(handoff_id=arguments["handoff_id"])
        if record is None:
            raise HTTPException(404, "Issued handoff not found")
        _same_project(record["handoff"]["thread_id"], project_id)
        marker = record.get("remote_delivery")
        if marker is not None:
            if marker != arguments:
                raise ManagementError(
                    "operation_conflict", "Delivery already has another binding"
                )
            return {"ok": True, "result": {"marker": marker, "duplicate": True}}
        if record["binding"] is not None:
            raise ManagementError(
                "binding_conflict", "An existing run already owns this handoff"
            )
        record["remote_delivery"] = dict(arguments)
        core.store.save_issued_handoff(arguments["handoff_id"], record)
        return {"ok": True, "result": {"marker": dict(arguments), "duplicate": False}}


def scoped_call(core, project_id, tool, arguments):
    """Caller holds the tenant RLock; services own their transactions."""
    if (
        not isinstance(tool, str)
        or tool not in TOOLS
        or not isinstance(arguments, dict)
    ):
        raise HTTPException(400, "Unsupported handoff call")
    if tool == "reserve_handoff_delivery":
        return reserve_delivery(core, project_id, arguments)
    if tool == "issue_handoff":
        _same_project(arguments.get("id"), project_id)
        if isinstance(arguments.get("operation_id"), str):
            _issued(core, project_id, operation_id=arguments["operation_id"])
    elif tool == "get_issued_handoff":
        if set(arguments) not in ({"handoff_id"}, {"operation_id"}):
            raise HTTPException(400, "One exact handoff reference required")
        _issued(core, project_id, **arguments)
    elif tool in {
        "bind_handoff_run",
        "record_handoff_question",
        "answer_handoff_question",
    }:
        if not isinstance(arguments.get("handoff_id"), str):
            raise HTTPException(400, "Exact handoff reference required")
        _issued(core, project_id, handoff_id=arguments["handoff_id"])
    elif tool == "import_return":
        payload = arguments.get("payload")
        if not isinstance(payload, dict) or arguments.get("strict_binding") is not True:
            raise HTTPException(400, "Strict issued return binding required")
        _same_project(payload.get("thread_id"), project_id)
        if not isinstance(payload.get("handoff_id"), str):
            raise HTTPException(400, "Exact handoff reference required")
        _issued(core, project_id, handoff_id=payload["handoff_id"])
        if isinstance(payload.get("return_id"), str):
            _returned(core, project_id, payload["return_id"])
    else:
        if not isinstance(arguments.get("return_id"), str):
            raise HTTPException(400, "Exact return reference required")
        _returned(core, project_id, arguments["return_id"])
    # Keep the existing schema validation, immutable source/run checks and receipts.
    return McpBridge(core).call(tool, arguments)


def register(app, project, body):
    """Existing middleware supplies TLS, user/tenant scope and cookie CSRF."""

    def envelope(request, project_id, **extra):
        return {
            "format": FORMAT,
            "project_id": project_id,
            "subject_ref": subject_ref(request.state.user, project_id),
            **extra,
        }

    @app.get("/api/projects/{pid}/handoff")
    def capabilities(pid: str, request: Request):
        project(request, pid)
        return envelope(
            request,
            pid,
            tools=sorted(TOOLS - INTERACTIVE),
            unsupported_interactive_tools=sorted(INTERACTIVE),
            executes_agents=False,
        )

    @app.post("/api/projects/{pid}/handoff")
    async def handoff_call(pid: str, request: Request):
        value = await body(request, {"tool", "arguments"})
        tool = value.get("tool")
        if not isinstance(tool, str) or tool not in TOOLS:
            raise HTTPException(400, "Unsupported handoff call")
        # This server's owner bearer can also log in as a cookie session. Neither
        # transport proves an independent operator. Do not add a new rights engine.
        if tool in INTERACTIVE:
            raise HTTPException(
                403, "Independent operator route is unavailable in this slice"
            )

        def operation():
            _, core, lock = project(request, pid)
            with lock:
                result = scoped_call(core, pid, tool, value.get("arguments"))
                return envelope(request, pid, call=result)

        return await run_in_threadpool(operation)
