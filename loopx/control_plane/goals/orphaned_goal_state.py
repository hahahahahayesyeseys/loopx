"""Guard the goal-start flow when Goal state outlives its registry entry.

A project ``ACTIVE_GOAL_STATE.md`` for a goal id the project registry no longer
declares is not the ordinary "nothing to connect yet" case: continuing would hand
a fresh lane write authority over state an earlier lane left behind, under the
same human-readable id. The routes below are the project goal-state roots
``loopx.state_backup`` archives, so a reset that moved or kept one of them is
detected rather than silently reconnected.

This module owns the whole fence so ``loopx.bootstrap_command_pack`` keeps only
its wiring: the detected fact, the operator-facing gate, the packet fields that
must disappear over orphaned state, and the guided transaction's blocking shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...project_prompt import shell_arg

ACTIVE_GOAL_STATE_FILENAME = "ACTIVE_GOAL_STATE.md"

ORPHANED_GOAL_STATE_CONNECTION = "orphaned_goal_state"

ORPHANED_GOAL_STATE_GATE_SCHEMA_VERSION = "loopx_orphaned_goal_state_gate_v0"

REGISTRY_WITHOUT_GOAL_CONNECTION = "registry_without_goal"

NOT_CONNECTED_CONNECTION = "not_connected"

REGISTRY_WITHOUT_GOAL_REASON = "registry exists but no matching goal entry was found"

NOT_CONNECTED_REASON = "project-local .loopx/registry.json is missing"

# Project-local goal state has been written under each of these roots, so a goal
# absent from the registry can still own durable state in any of them. Ordered
# current route first; every match is reported, never merged or copied.
GOAL_STATE_ROOTS: tuple[tuple[str, ...], ...] = (
    (".loopx", "goals"),
    (".codex", "goals"),
    (".claude", "goals"),
    (".local", "goals"),
)

ORPHANED_GOAL_STATE_REASON = (
    "the project registry has no entry for this goal id, but goal state written for "
    "it still exists; connecting again would create a second authority over that state"
)

FORBIDDEN_UNTIL_RESOLVED = (
    "bootstrap",
    "agent_registration",
    "todo_write",
    "quota_spend",
    "host_loop_activation",
)

# The command-pack keys that carry a mutation continuation, including the four the
# onboarding entry contract treats as one connect -> writeback -> activate -> quota
# loop. Over orphaned state none of them may be offered, goal text or not.
MUTATION_CONTINUATION_COMMANDS = (
    "goal_start_connect_if_needed",
    "bootstrap_dry_run_preview",
    "bootstrap_after_user_confirmation",
    "goal_start_plan_prompt",
    "goal_start_refresh_state",
    "goal_start_host_loop_activation",
    "goal_start_quota_should_run",
)


def orphaned_goal_state_routes(project: Path, goal_id: str) -> list[str]:
    """List existing state files for ``goal_id`` as project-relative routes.

    Routes stay relative because this projection reaches host-facing packets; an
    absolute path would carry the operator's filesystem into those artifacts.
    """

    return [
        path.relative_to(project).as_posix()
        for path in (
            project.joinpath(*root).joinpath(goal_id, ACTIVE_GOAL_STATE_FILENAME)
            for root in GOAL_STATE_ROOTS
        )
        if path.is_file()
    ]


def orphaned_goal_state_projection(project: Path, goal_id: str) -> dict[str, Any] | None:
    """Return the orphaned-state fact for ``goal_id``, or ``None`` when nothing is orphaned."""

    routes = orphaned_goal_state_routes(project, goal_id)
    if not routes:
        return None
    return {
        "schema_version": ORPHANED_GOAL_STATE_GATE_SCHEMA_VERSION,
        "goal_id": goal_id,
        "state_file_routes": routes,
        "reason": ORPHANED_GOAL_STATE_REASON,
    }


def goal_connection_without_matching_entry(
    *,
    base_connection: dict[str, Any],
    project: Path,
    goal_id: str,
    state_file: Path,
    registry_exists: bool,
    absence_connection: str,
    absence_reason: str,
    known_goal_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Classify "no matching registry entry" as orphaned state or as ordinary absence.

    The absence half keeps the packet fields it carried before this fence existed,
    including which of them are present, so a fresh project is unaffected.
    """

    shared = {
        **base_connection,
        "registry_exists": registry_exists,
        "goal_id": goal_id,
        "goal_found": False,
        "state_file": str(state_file),
        "state_file_exists": state_file.exists(),
        "mutation_confirmation_required": True,
    }
    if known_goal_ids is not None:
        shared["known_goal_ids"] = known_goal_ids
    projection = orphaned_goal_state_projection(project, goal_id)
    if projection is None:
        return {
            **shared,
            "connection_state": absence_connection,
            "reason": absence_reason,
        }
    return {
        **shared,
        "orphaned_goal_state": projection,
        "connection_state": ORPHANED_GOAL_STATE_CONNECTION,
        "bootstrap_continuation_allowed": False,
        "reason": ORPHANED_GOAL_STATE_REASON,
    }


def registry_missing_goal_connection(**fields: Any) -> dict[str, Any]:
    """Classify the absence inside a readable, non-empty registry."""

    return goal_connection_without_matching_entry(
        absence_connection=REGISTRY_WITHOUT_GOAL_CONNECTION,
        absence_reason=REGISTRY_WITHOUT_GOAL_REASON,
        **fields,
    )


def unregistered_goal_connection(**fields: Any) -> dict[str, Any]:
    """Classify the absence when no readable registry declares any goal."""

    return goal_connection_without_matching_entry(
        registry_exists=False,
        absence_connection=NOT_CONNECTED_CONNECTION,
        absence_reason=NOT_CONNECTED_REASON,
        **fields,
    )


def orphaned_goal_state_gate(
    projection: dict[str, Any],
    *,
    project: str,
    command_prefix: str,
    status_command: str,
) -> dict[str, Any]:
    """Project the next steps orphaned state allows: inspect, then back up."""

    return {
        **projection,
        "resolution_routes": [
            {
                "route": "inspect_registry_and_state",
                "mutates": False,
                "command": status_command,
            },
            {
                "route": "preview_state_backup",
                "mutates": False,
                "command": "\n".join(
                    [
                        f"cd {shell_arg(project)}",
                        f"{command_prefix} backup-state --project . "
                        "--current-project-only",
                    ]
                ),
            },
        ],
        "execution_boundary": (
            "backup-state writes nothing until the operator adds --execute, which is "
            "the auditable archive the resolution depends on"
        ),
        "unavailable_resolution_routes": [
            {
                "route": "archive_project_local_state",
                "reason": (
                    "uninstall-project selects goals from the project registry and "
                    "archive-runtime selects a goal directory under the shared runtime "
                    "root, so neither reaches state the registry no longer declares"
                ),
            },
            {
                "route": "adopt_orphan_state",
                "reason": (
                    "re-registering the goal id is the second authority this fence "
                    "prevents; adoption needs an explicit instance identity first"
                ),
            },
        ],
        "forbidden_until_resolved": list(FORBIDDEN_UNTIL_RESOLVED),
    }


def fence_command_pack(command_pack: dict[str, Any], *, command_prefix: str) -> None:
    """Leave a command pack over orphaned state with no mutation continuation."""

    projection = command_pack["project_connection"].get("orphaned_goal_state")
    if projection is None:
        return
    gate = orphaned_goal_state_gate(
        projection,
        project=str(command_pack.get("project") or ""),
        command_prefix=command_prefix,
        status_command=str(command_pack["commands"]["status"]),
    )
    for key in MUTATION_CONTINUATION_COMMANDS:
        command_pack["commands"][key] = None
    safety = command_pack["safety_contract"]
    safety["orphaned_goal_state_blocks_continuation"] = True
    safety["mutation_requires_user_confirmation"] = True
    safety["explicit_goal_start_may_write_project_local_state"] = False
    safety["explicit_goal_start_must_activate_host_loop"] = False
    safety["host_loop_activation_allowed"] = False
    command_pack["orphaned_goal_state"] = gate
    command_pack["recommended_next_step"] = {
        "kind": "resolve_orphaned_goal_state",
        "requires_user_confirmation": True,
        "summary": ORPHANED_GOAL_STATE_REASON,
        "orphaned_goal_state_gate": gate,
    }


def guided_fence(gate: dict[str, Any]) -> dict[str, Any]:
    """The guided-transaction fields that replace every continuation step."""

    return {
        "blocked_by": ORPHANED_GOAL_STATE_CONNECTION,
        "orphaned_goal_state_gate": gate,
        "ordered_steps": [
            {
                "id": "inspect_connection",
                "kind": "read_only",
                "purpose": "resolve the requested project route and confirm the registry and orphaned state disagree",
            },
            {
                "id": "resolve_orphaned_goal_state",
                "kind": "orphaned_goal_state_gate",
                "resolution_routes": gate["resolution_routes"],
                "forbidden_until_resolved": gate["forbidden_until_resolved"],
                "purpose": (
                    "inspect the orphaned state and preview its backup, then stop for "
                    "the operator's explicit resolution; do not bootstrap over it"
                ),
            },
        ],
    }


def render_guided_lines(transaction: dict[str, Any]) -> str:
    """Render the orphan gate section of the guided Markdown, or nothing."""

    gate = transaction.get("orphaned_goal_state_gate")
    if not isinstance(gate, dict):
        return ""
    routes = "\n".join(
        [
            f"- `{route.get('route')}` (preview only): "
            f"`{str(route.get('command')).splitlines()[-1]}`"
            for route in gate.get("resolution_routes") or []
            if isinstance(route, dict)
        ]
        + [
            f"- `{item.get('route')}` is not available yet: {item.get('reason')}"
            for item in gate.get("unavailable_resolution_routes") or []
            if isinstance(item, dict)
        ]
    )
    return (
        "\n## Orphaned Goal State Gate\n\n"
        f"{gate.get('reason')}\n\n"
        f"- orphaned state: {', '.join(f'`{route}`' for route in gate.get('state_file_routes') or [])}\n"
        f"- blocked until resolved: {', '.join(f'`{name}`' for name in gate.get('forbidden_until_resolved') or [])}\n"
        f"- {gate.get('execution_boundary')}\n\n"
        + routes
        + "\n"
    )
