"""Which roles each user holds."""

ROLE_PERMISSIONS = {
    "viewer": frozenset({"read"}),
    "author": frozenset({"read", "write"}),
    "editor": frozenset({"read", "write", "publish"}),
}


class Roles:
    """Every user's roles. Grants and revocations take effect at once."""

    def __init__(self):
        self._roles = {}
        self.version = 0  # bumped on every change, so caches can tell

    def grant(self, user, role):
        if role not in ROLE_PERMISSIONS:
            raise ValueError(f"unknown role {role!r}")
        self._roles.setdefault(user, set()).add(role)
        self.version += 1

    def revoke(self, user, role):
        self._roles.get(user, set()).discard(role)
        self.version += 1

    def roles_of(self, user):
        return frozenset(self._roles.get(user, ()))
