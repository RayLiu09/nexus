"""Bootstrap the initial platform administrator account.

The repository ships no seed admin (Alembic migrations do not insert
`user_account` rows). Run this script once after applying migrations to a
fresh database so an operator can sign in to the console.

Credentials are read from environment variables to avoid hard-coding
secrets in the repo or shell history:

    USER_NAME       desired username (required)
    USER_PASSWORD   plaintext password to hash with bcrypt (required)

Usage:

    cd nexus-app
    USER_NAME=admin USER_PASSWORD='change-me' \\
        uv run python -m nexus_app.scripts.bootstrap_admin

Re-running with the same username updates the password and re-activates
the account; pass --no-update to refuse overwriting an existing row.
"""

from __future__ import annotations

import argparse
import os
import sys

from nexus_app import auth_service, models
from nexus_app.database import get_session_local
from nexus_app.enums import PrincipalStatus, UserRole


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.stderr.write(f"error: environment variable {name} is required\n")
        sys.exit(2)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--display-name",
        default="Platform Admin",
        help="display name for the account (default: 'Platform Admin')",
    )
    parser.add_argument(
        "--no-update",
        action="store_true",
        help="exit non-zero if a user with the same username already exists",
    )
    args = parser.parse_args()

    username = _require_env("USER_NAME")
    password = _require_env("USER_PASSWORD")

    Session = get_session_local()
    with Session() as session:
        existing = session.query(models.UserAccount).filter_by(username=username).one_or_none()
        password_hash = auth_service.hash_password(password)

        if existing is None:
            user = models.UserAccount(
                username=username,
                display_name=args.display_name,
                role=UserRole.PLATFORM_DATA_ADMIN,
                status=PrincipalStatus.ACTIVE,
                password_hash=password_hash,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            print(f"created  username={user.username}  id={user.id}  role={user.role.value}")
            return 0

        if args.no_update:
            sys.stderr.write(
                f"error: user '{username}' already exists (id={existing.id}); "
                "rerun without --no-update to refresh password/status\n"
            )
            return 1

        existing.password_hash = password_hash
        existing.role = UserRole.PLATFORM_DATA_ADMIN
        existing.status = PrincipalStatus.ACTIVE
        if not existing.display_name:
            existing.display_name = args.display_name
        session.commit()
        print(f"updated  username={existing.username}  id={existing.id}  role={existing.role.value}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
