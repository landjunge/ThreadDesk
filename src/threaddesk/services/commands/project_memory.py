"""Project memory uses the existing command transports and workspace read grant."""

from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.project_memory import SCHEMA, read


def specifications():
    yield CommandSpec(
        "project.memory",
        "project",
        "Read a bounded snapshot of explicitly assigned project threads, saved "
        "re-entry, knowledge and recent reports. Never executes agents. "
        "Use expected_snapshot for consistent pagination; sources remain unverified.",
        SCHEMA,
        read,
    )
