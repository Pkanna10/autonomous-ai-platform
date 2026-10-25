"""Hidden check for accessctl: grants and revocations take effect at once."""

import unittest

from accessctl.access import AccessControl, PermissionDeniedError
from accessctl.roles import Roles


class HiddenCheck(unittest.TestCase):
    def test_a_grant_takes_effect_at_once(self):
        roles = Roles()
        roles.grant("bob", "author")
        access = AccessControl(roles)
        access.require("bob", "write")
        roles.grant("bob", "editor")
        access.require("bob", "publish")

    def test_a_revocation_takes_effect_at_once(self):
        roles = Roles()
        roles.grant("eve", "editor")
        access = AccessControl(roles)
        access.require("eve", "publish")
        roles.revoke("eve", "editor")
        with self.assertRaises(PermissionDeniedError):
            access.require("eve", "publish")
        self.assertEqual(access.permissions("eve"), frozenset())

    def test_other_users_are_unaffected(self):
        roles = Roles()
        roles.grant("ann", "viewer")
        access = AccessControl(roles)
        self.assertEqual(access.permissions("ann"), {"read"})
        roles.grant("bob", "editor")
        self.assertEqual(access.permissions("ann"), {"read"})
        self.assertEqual(access.permissions("bob"), {"read", "write", "publish"})


if __name__ == "__main__":
    unittest.main()
