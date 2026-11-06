"""Two-step idea intake on the shared preview/start command contracts."""

from __future__ import annotations

from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from threaddesk.core import i18n
from threaddesk.core.errors import ManagementError, ThreadDeskError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.thread_management import ID


def project_start_router(
    service_factory, templates, language, register, browser_strings
):
    router = APIRouter()

    def render(
        request, values=None, *, draft=False, error=None, status=200, status_url=None
    ):
        values = dict(values or {})
        lang = i18n.normalise(values.get("lang") or language(request))
        mode = i18n.normalise_register(values.get("mode") or register(request))
        if "operation_id" not in values:
            values["operation_id"] = uuid4().hex
        return templates.TemplateResponse(
            request,
            "project_start.html",
            {
                "request": request,
                "lang": lang,
                "register": mode,
                "browser_strings": browser_strings(lang, mode),
                "intake": values,
                "draft": draft,
                "intake_error": i18n.translate(error, lang, mode) if error else None,
                "status_url": status_url,
            },
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/projects/new")
    def new_project(request: Request):
        return render(request)

    def submit(save):
        async def endpoint(request: Request):
            form = await request.form()
            values = {
                key: value for key, value in form.items() if isinstance(value, str)
            }
            svc = None
            try:
                allowed = {
                    "title",
                    "idea",
                    "operation_id",
                    "lang",
                    "mode",
                    "csrf_token",
                }
                if save:
                    allowed |= {
                        "goals",
                        "next_steps",
                        "open_questions",
                        "expected_revision",
                    }
                if set(form) - allowed or any(
                    len(form.getlist(key)) != 1 for key in form
                ):
                    raise ManagementError(
                        "validation_error", "Unexpected project form fields."
                    )
                operation = values.get("operation_id", "")
                if not ID.fullmatch(operation) or (
                    save and values.get("expected_revision") != "0"
                ):
                    raise ManagementError(
                        "precondition_required", "Refresh the project form."
                    )
                lang = i18n.normalise(values.get("lang") or language(request))
                args = {
                    "idea": values.get("idea", ""),
                    "language": lang,
                    "source_ref": "local:project-start-form",
                    "source_revision": operation,
                }
                if values.get("title", "").strip():
                    args["title"] = values["title"]
                if save:
                    args["plan"] = {
                        key: [
                            line.strip()
                            for line in values.get(key, "").splitlines()
                            if line.strip()
                        ]
                        for key in ("goals", "next_steps", "open_questions")
                    }
                svc = service_factory()
                # The largest schema-valid Unicode draft may exceed a normal
                # command page. The HTML view renders that bounded draft once;
                # CLI/MCP retain their normal readback pagination.
                app = CommandApplication(
                    svc,
                    transport="http",
                    result_budget=128000,
                    allowed_scopes={"workspace.read", "workspace.write"},
                )
                req = {
                    "version": 1,
                    "workspace_id": app.workspace_id,
                    "command": "project.start" if save else "project.preview",
                    "arguments": args,
                }
                if save:
                    req.update(operation_id=operation, expected_revision=0)
                result = app.call(req, read_only=not save)["result"]
                if save:
                    query = urlencode(
                        {
                            "project_id": result["project_id"],
                            "lang": lang,
                            "mode": values.get("mode", "plain"),
                        }
                    )
                    response = RedirectResponse("/projects?" + query, status_code=303)
                    response.headers["X-ThreadDesk-Operation"] = operation
                    return response
                values.update(title=result["title"], idea=result["idea"])
                values.update(
                    {key: "\n".join(items) for key, items in result["plan"].items()}
                )
                return render(request, values, draft=True)
            except ThreadDeskError as exc:
                code = getattr(exc, "code", "validation_error")
                uncertain = code in {
                    "command_unconfirmed",
                    "operation_unconfirmed",
                    "operation_conflict",
                } or (save and code == "invalid_state")
                status_url = (
                    "/projects/start-status/" + values["operation_id"]
                    if uncertain and ID.fullmatch(values.get("operation_id", ""))
                    else None
                )
                if code == "secret_rejected":
                    values = {
                        key: value
                        for key, value in values.items()
                        if key in {"operation_id", "lang", "mode"}
                    }
                return render(
                    request,
                    values,
                    draft=save,
                    error="project.start.uncertain"
                    if uncertain
                    else "project.start.error",
                    status=409 if uncertain else 400,
                    status_url=status_url,
                )
            finally:
                if svc is not None and hasattr(svc.store, "connection"):
                    svc.store.connection.close()

        return endpoint

    router.add_api_route("/projects/preview", submit(False), methods=["POST"])
    router.add_api_route("/projects/start", submit(True), methods=["POST"])

    @router.get("/projects/start-status/{operation_id}")
    def start_status(request: Request, operation_id: str):
        svc = service_factory()
        try:
            record = CommandApplication(svc).operation(operation_id)
            result = record.get("result")
            if (
                record.get("state") == "complete"
                and isinstance(result, dict)
                and result.get("format") == "threaddesk.project-start.v1"
            ):
                return RedirectResponse(
                    "/projects?"
                    + urlencode(
                        {
                            "project_id": result["project_id"],
                            "lang": language(request),
                            "mode": register(request),
                        }
                    ),
                    status_code=303,
                )
            return render(
                request,
                {"operation_id": operation_id},
                error="project.start.not_confirmed",
                status=409,
            )
        except ThreadDeskError:
            return render(
                request,
                {"operation_id": operation_id},
                error="project.start.not_confirmed",
                status=400,
            )
        finally:
            if hasattr(svc.store, "connection"):
                svc.store.connection.close()

    return router
