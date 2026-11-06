"""Read-only project view using the same command as CLI and MCP clients."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request

from threaddesk.core import i18n
from threaddesk.core.errors import ThreadDeskError
from threaddesk.services.commands import CommandApplication


def project_memory_router(
    service_factory, templates, language, register, browser_strings
):
    router = APIRouter()

    @router.get("/projects")
    # FastAPI evaluates these hints on supported Python 3.9 runtimes.
    def projects(
        request: Request,
        project_id: Optional[str] = None,  # noqa: UP045
        include_archived: bool = False,
        offset: int = 0,
        expected_snapshot: Optional[str] = None,  # noqa: UP045
    ):
        svc = service_factory()
        lang, mode = language(request), register(request)
        context = {
            "request": request,
            "lang": lang,
            "register": mode,
            "browser_strings": browser_strings(lang, mode),
            "memory": None,
            "project_id": project_id,
            "include_archived": include_archived,
            "memory_error": None,
        }
        status = 200
        try:
            context["projects"] = sorted(
                (node for node in svc.list_nodes() if node.kind == "project"),
                key=lambda node: (node.title.casefold(), node.id),
            )
            if project_id:
                app = CommandApplication(
                    svc, allowed_scopes={"workspace.read"}, transport="http"
                )
                args = {
                    "project_id": project_id,
                    "include_archived": include_archived,
                    "offset": offset,
                }
                if expected_snapshot is not None:
                    args["expected_snapshot"] = expected_snapshot
                context["memory"] = app.call(
                    {
                        "version": 1,
                        "workspace_id": app.workspace_id,
                        "command": "project.memory",
                        "arguments": args,
                    },
                    read_only=True,
                )["result"]
            if context["memory"] and context["memory"]["next_offset"] is not None:
                context["next_page"] = str(
                    request.url.include_query_params(
                        offset=context["memory"]["next_offset"],
                        expected_snapshot=context["memory"]["snapshot"],
                    )
                )
        except ThreadDeskError as exc:
            conflict = getattr(exc, "code", "") == "snapshot_conflict"
            status = 409 if conflict else 400
            context["memory_error"] = i18n.translate(
                "project.memory.changed" if conflict else "project.memory.error",
                lang,
                mode,
            )
        finally:
            if hasattr(svc.store, "connection"):
                svc.store.connection.close()
        return templates.TemplateResponse(
            request,
            "projects.html",
            context,
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )

    return router
