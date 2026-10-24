"""Logging setup and startup configuration diagnostics."""

import json
import logging
import os

from tunnel_sync.configuration.validation import detect_env_typos, validate_tunnel_uuid

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)


class HealthCheckFilter(logging.Filter):
    """Filter to suppress /health access logs unless LOG_LEVEL is DEBUG."""

    def filter(self, record: logging.LogRecord) -> bool:
        if os.getenv("LOG_LEVEL", "INFO").upper() == "DEBUG":
            return True
        try:
            if isinstance(record.args, tuple) and len(record.args) >= 3:
                req_path = str(record.args[2])
                if req_path == "/health" or req_path.startswith("/health?"):
                    return False
            msg = record.getMessage()
            if " /health " in msg or " /health?" in msg or '"/health"' in msg or '"/health ' in msg:
                return False
        except Exception:
            # If inspection fails unexpectedly, do not drop the log record
            pass
        return True


class JsonLogFormatter(logging.Formatter):
    """Structured JSON log formatter for machine-readable logging (Loki, Datadog)."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_application_logging():
    log_format = os.getenv("LOG_FORMAT", "text").strip().lower()
    root_logger = logging.getLogger()
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)

    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    handler.addFilter(HealthCheckFilter())
    root_logger.addHandler(handler)
    root_logger.setLevel(LOG_LEVEL)


def perform_startup_validation(exit_on_error: bool = False, settings=None):
    """Perform environment typo detection and tunnel UUID format validation (Issue #54)."""
    environment = os.environ if settings is None else settings.environment
    warnings = detect_env_typos(dict(environment))
    tunnel_id = environment.get("CLOUDFLARE_TUNNEL_ID")
    if tunnel_id:
        is_valid, err = validate_tunnel_uuid(tunnel_id)
        if not is_valid:
            logger.critical("Configuration validation error: %s", err)
            if exit_on_error:
                import sys

                sys.exit(1)
            if err is not None:
                warnings.append(err)
    return warnings


logger = logging.getLogger("cf-tunnel-sync")
logger.setLevel(LOG_LEVEL)
