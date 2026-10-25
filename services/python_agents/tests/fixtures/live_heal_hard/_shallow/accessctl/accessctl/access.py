"""Permission checks."""

from accessctl.roles import ROLE_PERMISSIONS


class PermissionDeniedError(Exception):
    pass


class AccessControl:
    """Checks what users may do. Working out a user's permissions walks all
    their roles, so the result is cached per user."""

    def __init__(self, roles):
        self.roles = roles
        self._cache = {}

    def permissions(self, user):
        if user not in self._cache:
            granted = (ROLE_PERMISSIONS[r] for r in self.roles.roles_of(user))
            self._cache[user] = frozenset().union(*granted)
        return self._cache[user]

    def require(self, user, permission):
        if permission not in self.permissions(user):
            self._cache.pop(user, None)  # a grant may have come in since
            if permission not in self.permissions(user):
                raise PermissionDeniedError(f"{user} may not {permission}")
