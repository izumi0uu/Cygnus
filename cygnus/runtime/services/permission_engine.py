"""Permission Engine — runtime access decisions for Cygnus shell surfaces.

Ownership:
- this module resolves runtime-side access decisions for imported shell routes, MCP tools, and workspace membership checks
- permission vocabulary may be reused elsewhere, but access resolution remains runtime wiring truth

Global Realm:
  - Permissions are scoped: resource:action:own_dept or resource:action:all
  - own_dept = user belongs to at least one department that the resource is
    scoped to (via source_departments / skill_departments). Employees can be
    members of multiple departments — see EmployeeDepartment.
  - all = no scope restriction
  - No departments on resource = Global (visible to everyone with the action permission)

Workspace Realm:
  - Pure membership check. Global role does NOT grant access.
  - Admin (role='admin') can view all workspaces.
  - Workspace role (viewer/contributor/editor/admin) determines actions within workspace.
"""

from typing import Optional

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import (
    Employee,
    Skill,
    Source,
    SourceDepartment,
    WikiPage,
)

# ---------------------------------------------------------------------------
# Permission string parsing
# ---------------------------------------------------------------------------

def parse_permission(perm: str) -> tuple[str, str, str]:
    """Parse 'resource:action:scope' → (resource, action, scope).
    For org permissions like 'org:departments:read' → ('org', 'departments', 'read').
    """
    parts = perm.split(":")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return perm, "", ""


def has_permission(permissions: list[str], resource: str, action: str, scope: str = "any") -> bool:
    """Check if a permission list contains the required permission.
    
    scope = "any" → matches either own_dept or all
    scope = "all" → only matches :all
    scope = "own_dept" → matches :own_dept or :all
    """
    perm_all = f"{resource}:{action}:all"
    perm_own = f"{resource}:{action}:own_dept"

    if scope == "all":
        return perm_all in permissions
    elif scope == "own_dept":
        return perm_all in permissions or perm_own in permissions
    else:  # "any"
        return perm_all in permissions or perm_own in permissions


def has_any_permission(permissions: list[str], resource: str, action: str) -> bool:
    """Check if user has any variant (own_dept or all) of a resource:action."""
    return has_permission(permissions, resource, action, "any")


def get_scope_level(permissions: list[str], resource: str, action: str) -> Optional[str]:
    """Get the effective scope level for a resource:action.
    Returns 'all', 'own_dept', or None.
    """
    perm_all = f"{resource}:{action}:all"
    perm_own = f"{resource}:{action}:own_dept"
    if perm_all in permissions:
        return "all"
    if perm_own in permissions:
        return "own_dept"
    return None


# ---------------------------------------------------------------------------
# Global Realm: Document access
# ---------------------------------------------------------------------------

async def can_access_document(
    db: AsyncSession,
    user: Employee,
    source: Source,
    action: str = "read",
) -> bool:
    """Check if user can perform action on a source document.

    Logic:
    1. Admin → always True
    2. User has doc:{action}:all → True
    3. User has doc:{action}:own_dept →
       a. Source has no departments (Global doc) → True
       b. Source has any department in user.department_ids → True
       c. Otherwise → False
    4. Otherwise → False
    """
    if user.role == "admin":
        return True

    permissions = _get_user_permissions(user)

    # Has :all scope
    if f"doc:{action}:all" in permissions:
        return True

    # Has :own_dept scope
    if f"doc:{action}:own_dept" not in permissions:
        return False

    # Check if source is global (no departments) or belongs to any of the
    # user's departments.
    dept_result = await db.execute(
        select(SourceDepartment.department_id)
        .where(SourceDepartment.source_id == source.id)
    )
    source_dept_ids = {row[0] for row in dept_result.all()}

    if not source_dept_ids:
        # No departments = Global doc
        return True

    user_dept_ids = set(user.department_ids)
    return bool(user_dept_ids & source_dept_ids)


def build_wiki_scope_clause(user: Employee, action: str = "read"):
    """Return the SQL clause limiting wiki rows to the user's governed scope.

    ``None`` means the user may read every wiki row. A user with no matching
    permission receives an always-false primary-key clause so callers can keep
    the permission decision inside their SQL statement.
    """
    if user.role == "admin":
        return None

    permissions = _get_user_permissions(user)
    scope_level = get_scope_level(list(permissions), "wiki", action)
    if scope_level == "all":
        return None

    if scope_level == "own_dept":
        department_ids = list(user.department_ids)
        department_clause = (
            WikiPage.scope_id.in_(department_ids)
            if department_ids
            else WikiPage.id.is_(None)
        )
        return or_(
            WikiPage.scope_type == "global",
            and_(
                WikiPage.scope_type == "department",
                department_clause,
            ),
        )

    return WikiPage.id.is_(None)


def build_document_scope_clause(user: Employee, action: str = "read"):
    """Return the SQL clause limiting source rows to the user's governed scope.

    Sources without department links are global. ``None`` means unrestricted
    access; a user with no matching permission receives an always-false clause.
    """
    if user.role == "admin":
        return None

    permissions = _get_user_permissions(user)
    scope_level = get_scope_level(list(permissions), "doc", action)
    if scope_level == "all":
        return None

    if scope_level == "own_dept":
        global_clause = ~exists(
            select(SourceDepartment.source_id).where(
                SourceDepartment.source_id == Source.id,
            )
        )
        department_ids = list(user.department_ids)
        if not department_ids:
            return global_clause
        return or_(
            global_clause,
            exists(
                select(SourceDepartment.source_id).where(
                    SourceDepartment.source_id == Source.id,
                    SourceDepartment.department_id.in_(department_ids),
                )
            ),
        )

    return Source.id.is_(None)


# ---------------------------------------------------------------------------
# Global Realm: AI Skill access
# ---------------------------------------------------------------------------

async def can_access_skill(
    db: AsyncSession,
    user: Employee,
    skill: Skill,
    action: str = "read",
) -> bool:
    """Check if user can perform action on an AI skill.

    Logic:
    1. Admin → True
    2. User has skill:{action}:all → True
    3. User has skill:{action}:own_dept →
       a. Skill has no department (Global) → True
       b. Any of the skill's departments is in user.department_ids → True
       c. Otherwise → False
    4. Otherwise → False
    """
    if user.role == "admin":
        return True

    permissions = _get_user_permissions(user)

    if f"skill:{action}:all" in permissions:
        return True

    # Skill visible if it's Global (no depts) OR any overlap with user's depts.
    skill_dept_ids = {sd.department_id for sd in skill.departments}
    if not skill_dept_ids:
        return True

    return bool(set(user.department_ids) & skill_dept_ids)


def build_skill_filter(user: Employee, action: str = "read"):
    """Build SQLAlchemy filter clauses for listing skills.
    Returns: (needs_filter: bool, filter_clauses: list)
    """
    if user.role == "admin":
        return False, []

    permissions = _get_user_permissions(user)

    if f"skill:{action}:all" in permissions:
        return False, []

    if f"skill:{action}:own_dept" in permissions:
        # Filter: skill has no department (global) OR any overlap with user's depts.
        # SkillService.list_skills consumes allowed_department_ids as the union set.
        return True, list(user.department_ids)

    return True, None





# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_permissions(user: Employee) -> set[str]:
    """Extract effective permissions from user's fixed system role."""
    from cygnus.runtime.services.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS_MAP
    
    if user.role == "admin" or getattr(user, "global_role", None) == "admin":
        return set(ALL_PERMISSIONS)

    g_role = getattr(user, "global_role", "viewer") or "viewer"
    stored = ROLE_PERMISSIONS_MAP.get(g_role, ROLE_PERMISSIONS_MAP["viewer"])

    return set(stored)


def get_effective_permissions(user: Employee) -> list[str]:
    """Public version — returns sorted list for API responses."""
    from cygnus.runtime.services.permissions import ALL_PERMISSIONS
    perms = _get_user_permissions(user)
    return sorted(p for p in perms if p in ALL_PERMISSIONS)
