"""Project memory uses the existing command transports and workspace read grant."""

from threaddesk.services import project_plan, project_start
from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.project_memory import SCHEMA, read


def specifications():
    yield CommandSpec(
        "project.plan.get",
        "project",
        "Read a current or historical plan, provenance and live re-entry; no execution.",
        project_plan.READ_SCHEMA,
        project_plan.get,
    )
    yield CommandSpec(
        "project.plan.revise",
        "project",
        "Atomically revise a project plan with thread CAS and complete knowledge binding; no execution.",
        project_plan.WRITE_SCHEMA,
        project_plan.revise,
        effect="data",
        scope="workspace.write",
        revision_target="thread_id",
        affects_index=True,
    )
    yield CommandSpec(
        "project.memory",
        "project",
        "Read a bounded snapshot of explicitly assigned project threads, saved "
        "re-entry, knowledge and recent reports. Never executes agents. "
        "Use expected_snapshot for consistent pagination; sources remain unverified.",
        SCHEMA,
        read,
    )
    yield CommandSpec(
        "project.preview",
        "project",
        "Prepare an editable local project outline from an idea or supplied plan. "
        "Does not save data, call a model or start work.",
        project_start.SCHEMA,
        project_start.preview,
    )
    yield CommandSpec(
        "project.start",
        "project",
        "Atomically save an idea as a project, assigned thread and draft knowledge. "
        "Preserves the active thread. Does not execute agents or authorize tasks.",
        project_start.SCHEMA,
        project_start.start,
        effect="data",
        scope="workspace.write",
        revision_target="create",
        affects_index=True,
    )
