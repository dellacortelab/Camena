"""Runtime settings, all from environment variables.

Nothing here has a secret default: a missing passcode stops the app at
startup rather than letting it run open on the internet. Owner name and
timezone are only defaults; the setup screen stores the owner's choices in the
database and they are applied on top of these at startup.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass
class Settings:
    data_dir: Path
    passcode: str
    jwt_secret: str
    timezone: ZoneInfo
    owner_name: str
    model: str | None
    quick_model: str | None
    vapid_contact: str
    session_idle_minutes: int
    task_timeout_seconds: int
    frontend_dir: Path
    extra_allowed_tools: list[str] = field(default_factory=list)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "camena.sqlite3"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "workspace"


def load_settings() -> Settings:
    passcode = _env("CAMENA_PASSCODE")
    if not passcode or len(passcode) < 6:
        raise RuntimeError(
            "CAMENA_PASSCODE must be set (6+ characters). Camena spends your Claude "
            "subscription, so it never runs without a lock."
        )
    data_dir = Path(_env("CAMENA_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    # The JWT secret persists in the data dir so logins survive restarts
    # without having to be configured.
    jwt_secret = _env("CAMENA_JWT_SECRET")
    if not jwt_secret:
        secret_file = data_dir / "jwt_secret"
        if not secret_file.exists():
            secret_file.write_text(secrets.token_urlsafe(48))
            secret_file.chmod(0o600)
        jwt_secret = secret_file.read_text().strip()

    default_frontend = Path(__file__).resolve().parents[2] / "frontend"
    extra = [t.strip() for t in (_env("CAMENA_EXTRA_ALLOWED_TOOLS", "") or "").split(",") if t.strip()]

    return Settings(
        data_dir=data_dir,
        passcode=passcode,
        jwt_secret=jwt_secret,
        timezone=ZoneInfo(_env("CAMENA_TIMEZONE", "America/Denver")),
        owner_name=_env("CAMENA_OWNER_NAME", "friend"),
        model=_env("CAMENA_MODEL"),
        quick_model=_env("CAMENA_QUICK_MODEL"),
        vapid_contact=_env("CAMENA_VAPID_CONTACT", "mailto:admin@example.com"),
        session_idle_minutes=int(_env("CAMENA_SESSION_IDLE_MINUTES", "20")),
        task_timeout_seconds=int(_env("CAMENA_TASK_TIMEOUT_SECONDS", "300")),
        frontend_dir=Path(_env("CAMENA_FRONTEND_DIR", str(default_frontend))),
        extra_allowed_tools=extra,
    )
