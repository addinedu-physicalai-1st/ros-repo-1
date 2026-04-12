"""RBAC: API-key authentication + role-based permission checks.

Flow:
  Client sends  Authorization: Bearer <api_key>
  Server SHA-256 hashes key → looks up users table
  Role → frozenset[Permission] checked per endpoint

Roles (from proto UserRole):
  CUSTOMER (1)     — create tasks, read own tasks
  STAFF_KITCHEN(2) — read all tasks, create tasks
  STAFF_FLOOR  (3) — read all tasks + robots + telemetry, create tasks
  ADMIN        (4) — everything + send commands + manage users
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

import aiosqlite
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from robotcafe.db.v1 import robotcafe_pb2 as pb

_bearer = HTTPBearer(auto_error=True)


class Permission(str, Enum):
    TASK_CREATE    = "task:create"
    TASK_READ_OWN  = "task:read:own"   # own requester_id only
    TASK_READ_ALL  = "task:read:all"
    ROBOT_READ     = "robot:read"
    ROBOT_COMMAND  = "robot:command"
    TELEMETRY_READ = "telemetry:read"
    USER_MANAGE    = "user:manage"
    PLACE_READ     = "place:read"      # GET /places, /menu-items (all roles)
    PLACE_MANAGE   = "place:manage"    # PATCH /places, PUT waypoints (ADMIN only)


ROLE_PERMISSIONS: dict[int, frozenset[Permission]] = {
    int(pb.UserRole.CUSTOMER): frozenset({
        Permission.TASK_CREATE,
        Permission.TASK_READ_OWN,
        Permission.PLACE_READ,
    }),
    int(pb.UserRole.STAFF_KITCHEN): frozenset({
        Permission.TASK_CREATE,
        Permission.TASK_READ_ALL,
        Permission.PLACE_READ,
    }),
    int(pb.UserRole.STAFF_FLOOR): frozenset({
        Permission.TASK_CREATE,
        Permission.TASK_READ_ALL,
        Permission.ROBOT_READ,
        Permission.TELEMETRY_READ,
        Permission.PLACE_READ,
    }),
    int(pb.UserRole.ADMIN): frozenset({
        Permission.TASK_CREATE,
        Permission.TASK_READ_ALL,
        Permission.ROBOT_READ,
        Permission.ROBOT_COMMAND,
        Permission.TELEMETRY_READ,
        Permission.USER_MANAGE,
        Permission.PLACE_READ,
        Permission.PLACE_MANAGE,
    }),
}


def hash_api_key(key: str) -> str:
    """SHA-256 of the raw key string."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    """Cryptographically random 64-char hex key (256 bits)."""
    return secrets.token_hex(32)


@dataclass
class CurrentUser:
    user_id: str
    name: str
    role: int
    prefix: str = ""

    def has(self, perm: Permission) -> bool:
        return perm in ROLE_PERMISSIONS.get(self.role, frozenset())

    @property
    def role_name(self) -> str:
        return pb.UserRole.Name(self.role)

    def __str__(self) -> str:
        return f"{self.user_id}({self.role_name})"


async def _lookup_user(request: Request, key_hash: str) -> Optional[CurrentUser]:
    from db import Database  # late import to avoid circular deps

    db: Database = request.app.state.db
    conn: aiosqlite.Connection = request.app.state.conn
    lock = request.app.state.db_lock
    async with lock:
        row = await db.get_user_by_key_hash(conn, key_hash)
    if row is None or not int(row["is_active"]):
        return None
    return CurrentUser(
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        role=int(row["role"]),
        prefix=str(row["prefix"] or ""),
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> CurrentUser:
    key_hash = hash_api_key(credentials.credentials)
    user = await _lookup_user(request, key_hash)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require(perm: Permission) -> Callable[..., Awaitable[CurrentUser]]:
    """Return a FastAPI dependency that enforces *perm* on the current user."""

    async def _guard(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has(perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role_name}' lacks permission '{perm.value}'",
            )
        return user

    return _guard
