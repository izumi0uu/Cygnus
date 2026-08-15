from __future__ import annotations

from types import SimpleNamespace
from typing import cast
import unittest

from cygnus.runtime.database.models import Employee
from cygnus.runtime.routers.rbac import get_role_catalog
from cygnus.runtime.services.permissions import (
    ALL_PERMISSIONS,
    PERMISSION_DESCRIPTIONS,
    PERMISSION_GROUPS,
    PERMISSION_LABELS,
    ROLE_PERMISSIONS_MAP,
)


class FixedRoleCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_projects_the_permission_engine_source_of_truth(self) -> None:
        admin = cast(
            Employee,
            cast(object, SimpleNamespace(role="admin", global_role="admin")),
        )

        catalog = await get_role_catalog(_user=admin)

        self.assertEqual(
            [role.id for role in catalog.roles], list(ROLE_PERMISSIONS_MAP)
        )
        self.assertEqual(
            {role.id: role.permissions for role in catalog.roles},
            ROLE_PERMISSIONS_MAP,
        )
        self.assertEqual(
            [group.id for group in catalog.groups], list(PERMISSION_GROUPS)
        )
        self.assertEqual(
            [
                permission.key
                for group in catalog.groups
                for permission in group.permissions
            ],
            ALL_PERMISSIONS,
        )

    async def test_catalog_includes_labels_and_descriptions_for_every_permission(
        self,
    ) -> None:
        admin = cast(
            Employee,
            cast(object, SimpleNamespace(role="admin", global_role="admin")),
        )

        catalog = await get_role_catalog(_user=admin)
        permissions = {
            permission.key: permission
            for group in catalog.groups
            for permission in group.permissions
        }

        self.assertEqual(set(permissions), set(ALL_PERMISSIONS))
        for key in ALL_PERMISSIONS:
            with self.subTest(permission=key):
                self.assertEqual(permissions[key].label, PERMISSION_LABELS[key])
                self.assertEqual(
                    permissions[key].description,
                    PERMISSION_DESCRIPTIONS[key],
                )


if __name__ == "__main__":
    unittest.main()
