"""Bounded plan editing and historical readback on the shared command surface."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from threaddesk.core import i18n
from threaddesk.core.errors import ManagementError, ThreadDeskError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.thread_management import ID


def project_plan_router(
    service_factory, templates, language, register, browser_strings
):
    router = APIRouter()

    def path(project_id, thread_id):
        return f"/projects/{project_id}/plan/{thread_id}"

    def render(
        request,
        project_id,
        thread_id,
        *,
        result=None,
        values=None,
        error=None,
        status=200,
        status_url=None,
    ):
        values = dict(values or {})
        lang = i18n.normalise(values.get("lang") or language(request))
        mode = i18n.normalise_register(values.get("mode") or register(request))
        if "operation_id" not in values:
            values["operation_id"] = uuid4().hex
        # History is frozen; edit fields come only from the separate current live view.
        if result and not values.get("expected_basis"):
            values.update(
                expected_revision=str(result["thread_revision"]),
                expected_plan_revision=str(result["plan_revision"]),
                expected_basis=result["basis_digest"],
                summary=result["snapshot"]["summary"],
            )
            values.update(
                {
                    group: "\n".join(
                        item["title"] for item in result["live_plan"][group]
                    )
                    for group in ("goals", "next_steps", "open_questions")
                }
            )
        return templates.TemplateResponse(
            request,
            "project_plan.html",
            {
                "request": request,
                "lang": lang,
                "register": mode,
                "browser_strings": browser_strings(lang, mode),
                "plan_result": result,
                "intake": values,
                "plan_path": path(project_id, thread_id),
                "project_id": project_id,
                "thread_id": thread_id,
                "plan_error": i18n.translate(error, lang, mode) if error else None,
                "status_url": status_url,
            },
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/projects/{project_id}/plan/{thread_id}")
    def show(
        request: Request,
        project_id: str,
        thread_id: str,
        revision: Optional[int] = None,  # noqa: UP045 -- FastAPI on supported Python 3.9
        offset: int = 0,
        expected_plan_revision: Optional[int] = None,  # noqa: UP045
    ):
        svc = service_factory()
        try:
            app = CommandApplication(
                svc,
                transport="http",
                result_budget=2 * 1024 * 1024,
                allowed_scopes={"workspace.read"},
            )
            args = {"project_id": project_id, "thread_id": thread_id, "offset": offset}
            if revision is not None:
                args["revision"] = revision
            if expected_plan_revision is not None:
                args["expected_plan_revision"] = expected_plan_revision
            result = app.call(
                {
                    "version": 1,
                    "workspace_id": app.workspace_id,
                    "command": "project.plan.get",
                    "arguments": args,
                },
                read_only=True,
            )["result"]
            return render(request, project_id, thread_id, result=result)
        except ThreadDeskError:
            return render(
                request,
                project_id,
                thread_id,
                error="project.plan.read_error",
                status=409,
            )
        finally:
            if hasattr(svc.store, "connection"):
                svc.store.connection.close()

    @router.post("/projects/{project_id}/plan/{thread_id}")
    async def update(request: Request, project_id: str, thread_id: str):
        form = await request.form()
        values = {key: value for key, value in form.items() if isinstance(value, str)}
        svc = None
        try:
            allowed = {
                "csrf_token",
                "operation_id",
                "expected_revision",
                "expected_plan_revision",
                "expected_basis",
                "summary",
                "reason",
                "goals",
                "next_steps",
                "open_questions",
                "lang",
                "mode",
            }
            if set(form) - allowed or any(len(form.getlist(key)) != 1 for key in form):
                raise ManagementError(
                    "validation_error", "Unexpected plan form fields."
                )
            operation = values.get("operation_id", "")
            if not ID.fullmatch(operation):
                raise ManagementError(
                    "validation_error", "A stable operation identity is required."
                )
            try:
                expected, plan_revision = (
                    int(values["expected_revision"]),
                    int(values["expected_plan_revision"]),
                )
            except (KeyError, ValueError):
                raise ManagementError(
                    "validation_error", "The plan basis is required."
                ) from None
            args = {
                "project_id": project_id,
                "thread_id": thread_id,
                "expected_plan_revision": plan_revision,
                "expected_basis": values.get("expected_basis", ""),
                "source_ref": "local:project-plan-form",
                "source_revision": operation,
                "reason": values.get("reason", ""),
                "summary": values.get("summary", ""),
                "plan": {
                    group: [
                        line.strip()
                        for line in values.get(group, "").splitlines()
                        if line.strip()
                    ]
                    for group in ("goals", "next_steps", "open_questions")
                },
            }
            svc = service_factory()
            app = CommandApplication(
                svc, transport="http", allowed_scopes={"workspace.write"}
            )
            app.call(
                {
                    "version": 1,
                    "workspace_id": app.workspace_id,
                    "command": "project.plan.revise",
                    "operation_id": operation,
                    "expected_revision": expected,
                    "arguments": args,
                }
            )
            query = urlencode(
                {
                    "lang": i18n.normalise(values.get("lang") or language(request)),
                    "mode": i18n.normalise_register(
                        values.get("mode") or register(request)
                    ),
                }
            )
            response = RedirectResponse(
                path(project_id, thread_id) + "?" + query, status_code=303
            )
            response.headers["X-ThreadDesk-Operation"] = operation
            return response
        except ThreadDeskError as exc:
            code = getattr(exc, "code", "validation_error")
            uncertain = code in {
                "command_unconfirmed",
                "operation_unconfirmed",
                "operation_conflict",
                "invalid_state",
            }
            stale = code in {
                "revision_conflict",
                "plan_basis_conflict",
                "plan_state_conflict",
                "scope_conflict",
            }
            status_url = (
                path(project_id, thread_id) + "/operation/" + values["operation_id"]
                if uncertain and ID.fullmatch(values.get("operation_id", ""))
                else None
            )
            if code == "secret_rejected":
                values = {
                    key: value
                    for key, value in values.items()
                    if key
                    in {
                        "operation_id",
                        "lang",
                        "mode",
                        "expected_revision",
                        "expected_plan_revision",
                        "expected_basis",
                    }
                }
            return render(
                request,
                project_id,
                thread_id,
                values=values,
                error="project.plan.uncertain"
                if uncertain
                else "project.plan.stale"
                if stale
                else "project.plan.error",
                status=409 if uncertain or stale else 400,
                status_url=status_url,
            )
        finally:
            if svc is not None and hasattr(svc.store, "connection"):
                svc.store.connection.close()

    @router.get("/projects/{project_id}/plan/{thread_id}/operation/{operation_id}")
    def operation_status(
        request: Request, project_id: str, thread_id: str, operation_id: str
    ):
        svc = service_factory()
        try:
            record = CommandApplication(svc).operation(operation_id)
            result = record.get("result")
            if (
                record.get("state") == "complete"
                and isinstance(result, dict)
                and result.get("format") == "threaddesk.project-plan-revised.v1"
                and result.get("project_id") == project_id
                and result.get("thread_id") == thread_id
            ):
                return RedirectResponse(path(project_id, thread_id), status_code=303)
            return render(
                request,
                project_id,
                thread_id,
                values={"operation_id": operation_id},
                error="project.plan.uncertain",
                status=409,
            )
        except ThreadDeskError:
            return render(
                request,
                project_id,
                thread_id,
                values={"operation_id": operation_id},
                error="project.plan.uncertain",
                status=400,
            )
        finally:
            if hasattr(svc.store, "connection"):
                svc.store.connection.close()

    return router
