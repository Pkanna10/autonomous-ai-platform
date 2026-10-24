"""The report's scenario for accessctl: bob publishes once made an editor."""

import unittest

from accessctl.access import AccessControl, PermissionDeniedError
from accessctl.roles import Roles


class ReportedCase(unittest.TestCase):
    def test_bob_publishes_after_the_grant(self):
        roles = Roles()
        access = AccessControl(roles)
        with self.assertRaises(PermissionDeniedError):
            access.require("bob", "publish")
        roles.grant("bob", "editor")
        access.require("bob", "publish")


if __name__ == "__main__":
    unittest.main()
