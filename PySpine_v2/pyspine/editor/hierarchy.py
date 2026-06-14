from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pyspine.core.model import Project
from pyspine.core.validation import ValidationError, validate_project


@dataclass(frozen=True, slots=True)
class HierarchyRow:
    """A display row for the rig hierarchy sidebar."""

    instance: str
    depth: int


@dataclass(frozen=True, slots=True)
class AttachmentCandidate:
    """A compatible child->parent attachment pair.

    The first version of the rigging UX intentionally prefers matching names
    because they are what make PySpine rigs predictable: head.neck attaches to
    shoulders.neck, forearm.left_elbow attaches to bicep.left_elbow, etc.
    """

    parent_point: str
    self_point: str

    @property
    def label(self) -> str:
        return f"{self.self_point} -> {self.parent_point}"


def children_by_parent(project: Project) -> dict[str | None, list[str]]:
    children: dict[str | None, list[str]] = defaultdict(list)
    for name, inst in project.rig.instances.items():
        children[inst.parent].append(name)
    for names in children.values():
        names.sort(key=lambda n: (project.rig.instances[n].z, n))
    return dict(children)


def hierarchy_rows(project: Project) -> list[HierarchyRow]:
    children = children_by_parent(project)
    rows: list[HierarchyRow] = []
    seen: set[str] = set()

    def walk(parent: str | None, depth: int) -> None:
        for name in children.get(parent, []):
            if name in seen:
                continue
            seen.add(name)
            rows.append(HierarchyRow(name, depth))
            walk(name, depth + 1)

    walk(None, 0)
    # If the project is temporarily invalid and contains instances whose parent
    # is missing, still surface them in the panel instead of hiding them.
    for name in sorted(project.rig.instances):
        if name not in seen:
            rows.append(HierarchyRow(name, 0))
    return rows


def root_instances(project: Project) -> list[str]:
    return [row.instance for row in hierarchy_rows(project) if project.rig.instances[row.instance].parent is None]


def would_cycle(project: Project, child_name: str, new_parent_name: str) -> bool:
    cur: str | None = new_parent_name
    while cur is not None:
        if cur == child_name:
            return True
        cur = project.rig.instances.get(cur).parent if cur in project.rig.instances else None
    return False


def matching_attachment_candidates(project: Project, child_instance: str, parent_instance: str) -> list[AttachmentCandidate]:
    if child_instance not in project.rig.instances or parent_instance not in project.rig.instances:
        return []
    child = project.rig.instances[child_instance]
    parent = project.rig.instances[parent_instance]
    if child.sprite not in project.sheet.sprites or parent.sprite not in project.sheet.sprites:
        return []
    child_points = project.sheet.sprites[child.sprite].points
    parent_points = project.sheet.sprites[parent.sprite].points
    common = set(child_points) & set(parent_points)
    ordered = sorted(p for p in common if p != "origin")
    if "origin" in common:
        ordered.append("origin")
    return [AttachmentCandidate(parent_point=p, self_point=p) for p in ordered]


def parent_candidates(project: Project, child_instance: str) -> list[tuple[str, list[AttachmentCandidate]]]:
    if child_instance not in project.rig.instances:
        return []
    out: list[tuple[str, list[AttachmentCandidate]]] = []
    for parent_name in sorted(project.rig.instances):
        if parent_name == child_instance or would_cycle(project, child_instance, parent_name):
            continue
        matches = matching_attachment_candidates(project, child_instance, parent_name)
        if matches:
            out.append((parent_name, matches))
    return out


def validation_report(project: Project) -> tuple[list[str], list[str], list[str]]:
    """Return (errors, warnings, info) for the sidebar validation panel."""
    try:
        warnings = validate_project(project, strict=True)
        errors: list[str] = []
    except ValidationError as exc:
        errors = [line for line in str(exc).splitlines() if line.strip()]
        warnings = []
    roots = root_instances(project)
    info = [f"roots: {len(roots)}" + (f" ({', '.join(roots[:4])}{'...' if len(roots) > 4 else ''})" if roots else "")]
    if not project.rig.instances:
        info.append("rig has no instances")
    return errors, warnings, info
