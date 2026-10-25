import unittest

from accessctl.access import AccessControl, PermissionDeniedError
from accessctl.roles import Roles


class AccessTest(unittest.TestCase):
    def test_an_editor_may_publish(self):
        roles = Roles()
        roles.grant("ann", "editor")
        AccessControl(roles).require("ann", "publish")

    def test_an_author_may_not_publish(self):
        roles = Roles()
        roles.grant("bo", "author")
        with self.assertRaises(PermissionDeniedError):
            AccessControl(roles).require("bo", "publish")

    def test_permissions_add_up(self):
        roles = Roles()
        roles.grant("cy", "viewer")
        roles.grant("cy", "author")
        self.assertEqual(AccessControl(roles).permissions("cy"), {"read", "write"})


if __name__ == "__main__":
    unittest.main()
