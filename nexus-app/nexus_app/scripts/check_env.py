from __future__ import annotations

import argparse
import json
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from nexus_app.config import Settings

SECRET_MARKERS = ("password", "secret", "token", "key", "credential")


@dataclass
class CheckResult:
    name: str
    target: str
    status: str
    detail: str


def redact(key: str, value: str | None) -> str | None:
    if value is None:
        return None
    if any(marker in key.lower() for marker in SECRET_MARKERS):
        return "***REDACTED***" if value else ""
    if "://" in value and "@" in value:
        scheme, rest = value.split("://", 1)
        _credentials, target = rest.rsplit("@", 1)
        return f"{scheme}://***REDACTED***@{target}"
    return value


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def check_socket(name: str, host: str, port: int, timeout: float = 3.0) -> CheckResult:
    target = f"{host}:{port}"
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return CheckResult(name, target, "ok", "tcp_connect_ok")
    except Exception as exc:
        return CheckResult(name, target, "failed", f"{type(exc).__name__}: {exc}")


def check_http(name: str, endpoint: str, timeout: float = 3.0) -> CheckResult:
    parsed = urlparse(endpoint)
    target = endpoint
    if not parsed.scheme or not parsed.netloc:
        return CheckResult(name, target, "failed", "invalid_url")

    request = Request(endpoint, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return CheckResult(name, target, "ok", f"http_{response.status}")
    except Exception as exc:
        return CheckResult(name, target, "failed", f"{type(exc).__name__}: {exc}")


def build_summary(settings: Settings, env_values: dict[str, str]) -> dict[str, object]:
    checks = [
        check_socket("postgres", settings.postgres_host, settings.postgres_port),
        check_socket("redis", settings.redis_host, settings.redis_port),
        check_socket("rabbitmq", settings.rabbitmq_host, settings.rabbitmq_port),
        check_http("minio", settings.minio_endpoint),
    ]
    if settings.mineru_endpoint:
        checks.append(check_http("mineru", settings.mineru_endpoint))
    if settings.ragflow_endpoint:
        checks.append(check_http("ragflow", settings.ragflow_endpoint))
    if settings.litellm_endpoint:
        checks.append(check_http("litellm", settings.litellm_endpoint))

    expected_keys = [
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "REDIS_HOST",
        "REDIS_PORT",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MINIO_BUCKET_PRIMARY",
        "RABBITMQ_HOST",
        "RABBITMQ_PORT",
        "RABBITMQ_VHOST",
        "RABBITMQ_USERNAME",
        "RABBITMQ_PASSWORD",
    ]

    missing = [key for key in expected_keys if key not in env_values or env_values[key] == ""]
    redacted_env = {
        key: redact(key, value)
        for key, value in env_values.items()
        if key in expected_keys
        or key.startswith(("MINERU_", "RAGFLOW_", "LITELLM_", "CELERY_", "NEXUS_", "APP_"))
    }

    config_warnings: list[str] = []
    if settings.postgres_driver == "postgresql":
        config_warnings.append(
            "POSTGRES_DRIVER=postgresql is accepted, but SQLAlchemy runtime URL is normalized to postgresql+psycopg."
        )
    if not settings.ragflow_api_key:
        config_warnings.append("RAGFLOW_API_KEY is empty; RAGFlow authenticated calls may fail.")
    if not settings.litellm_api_key:
        config_warnings.append("LITELLM_API_KEY is empty; LiteLLM authenticated calls may fail.")
    if "RABBITMQ_URL" in env_values and env_values.get("RABBITMQ_VHOST") not in {
        "",
        None,
        "/",
    }:
        if f"/{env_values['RABBITMQ_VHOST']}" not in env_values["RABBITMQ_URL"]:
            config_warnings.append("RABBITMQ_URL does not appear to include RABBITMQ_VHOST.")

    return {
        "env": redacted_env,
        "derived": {
            "database_url": redact("database_url", settings.database_url),
            "rabbitmq_url": redact("rabbitmq_url", settings.effective_rabbitmq_url),
        },
        "missing_required_keys": missing,
        "warnings": config_warnings,
        "checks": [result.__dict__ for result in checks],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="../.env.dev")
    args = parser.parse_args()

    env_path = Path(args.env_file).resolve()
    env_values = load_env_file(env_path)
    settings = Settings(_env_file=str(env_path))
    print(json.dumps(build_summary(settings, env_values), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
