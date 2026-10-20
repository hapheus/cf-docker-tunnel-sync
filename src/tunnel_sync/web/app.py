"""HTTP presentation and authentication over injected application container."""

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from tunnel_sync.application.preview import compute_preview
from tunnel_sync.web.auth import create_auth
from tunnel_sync.web.serializers import sanitize_sync_state, serialize_change_plan


def create_http_app(container, *, settings_provider=None):
    get_settings = settings_provider or (lambda: container.settings)

    @asynccontextmanager
    async def lifespan(app):
        from tunnel_sync.runtime.logging import perform_startup_validation, setup_application_logging

        setup_application_logging()
        perform_startup_validation(settings=container.settings)
        await container.scheduler.start()
        try:
            yield
        finally:
            await container.scheduler.close()

    app = FastAPI(title="Cloudflare Tunnel & DNS Sync", lifespan=lifespan)
    app.state.services = container

    @app.get("/health")
    @app.get("/healthz")
    def health():
        sync_state = container.snapshot()
        docker_ok = sync_state.get("docker_connected", True)
        status_str = "healthy" if docker_ok else "degraded"
        return {"status": status_str, "docker_connected": docker_ok, "sync_status": sync_state.get("status")}

    @app.get("/ready")
    def ready(response: Response):
        sync_state = container.snapshot()
        docker_ok = sync_state.get("docker_connected", True)
        if not docker_ok and response:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if docker_ok else "not ready",
            "docker_connected": docker_ok,
            "sync_status": sync_state.get("status"),
        }

    check_dashboard_auth, check_metrics_auth = create_auth(get_settings)

    def is_dashboard_enabled() -> bool:
        settings = get_settings()
        val = settings.get("DASHBOARD_ENABLED", settings.get("EMBEDDED_DASHBOARD_ENABLED", "true")).strip().lower()
        return val not in ("false", "0", "no", "disabled", "off")

    @app.get("/", response_class=HTMLResponse)
    @app.get("/dashboard", response_class=HTMLResponse)
    def get_dashboard(authenticated: bool = Depends(check_dashboard_auth)):
        if not is_dashboard_enabled():
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "status": "disabled",
                    "message": "Embedded dashboard UI is disabled. Use /api/status for API data.",
                },
            )
        static_file = os.path.join(os.path.dirname(__file__), "static", "index.html")
        headers = {
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "connect-src 'self'; "
                "img-src 'self' data:; "
                "object-src 'none'; "
                "base-uri 'self';"
            ),
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }
        if os.path.exists(static_file):
            with open(static_file, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read(), headers=headers)
        return HTMLResponse(
            content="<!DOCTYPE html><html><head><title>Cloudflare Tunnel Sync</title></head><body><h1>Cloudflare Tunnel Sync Dashboard</h1><p>Running in single-container mode. Access <a href='/api/status'>/api/status</a> for API data.</p></body></html>",
            headers=headers,
        )

    @app.get("/api/sync/preview")
    @app.get("/api/v1/sync/preview")
    def api_sync_preview(authenticated: bool = Depends(check_dashboard_auth)):
        sync_state = container.snapshot()
        settings = get_settings()
        plan_data = sync_state.get("last_change_plan")
        if plan_data:
            return JSONResponse({"status": "cached", "plan": plan_data})

        plan = compute_preview(
            settings,
            sync_state,
            container.discovery.discover,
            zone_id=settings.get("CLOUDFLARE_ZONE_ID") or "preview-zone-id",
        )
        return JSONResponse({"status": "computed", "plan": plan.model_dump()})

    @app.get("/api/status")
    def api_status(authenticated: bool = Depends(check_dashboard_auth)):
        sync_state = container.status()
        return JSONResponse(sanitize_sync_state(sync_state))

    @app.get("/api/events")
    def api_events(
        severity: Optional[str] = None,
        service: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 100,
        authenticated: bool = Depends(check_dashboard_auth),
    ):
        """Retrieve audit event timeline entries with optional severity, service, and text filters (Issue #120)."""
        sync_state = container.snapshot()
        events = list(sync_state.get("events", []))
        if severity:
            sev_lower = severity.strip().lower()
            events = [e for e in events if e.get("severity", "").lower() == sev_lower]
        if service:
            svc_lower = service.strip().lower()
            events = [e for e in events if svc_lower in e.get("service", "").lower()]
        if q:
            query = q.strip().lower()
            events = [
                e
                for e in events
                if query in e.get("message", "").lower()
                or query in e.get("event_type", "").lower()
                or query in e.get("service", "").lower()
            ]
        limit = max(1, min(limit, 100))
        return JSONResponse({"events": events[:limit], "total": len(events)})

    @app.get("/api/history")
    def api_history(limit: int = 20, authenticated: bool = Depends(check_dashboard_auth)):
        """Retrieve execution duration and status history ring-buffer entries (Issue #119)."""
        sync_state = container.snapshot()
        history = list(sync_state.get("sync_history", []))
        limit = max(1, min(limit, 20))
        return JSONResponse({"history": history[:limit], "total": len(history)})

    @app.get("/api/notifications/status")
    def api_notifications_status(authenticated: bool = Depends(check_dashboard_auth)):
        """Retrieve webhook notification dispatch status and cooldown state (Issue #121)."""
        sync_state = container.snapshot()
        try:
            sync_state["alert_status"] = container.dispatcher.get_status()
        except Exception:
            pass
        return JSONResponse(sync_state.get("alert_status", {}))

    @app.get("/metrics", response_class=PlainTextResponse)
    def get_prometheus_metrics(authenticated: bool = Depends(check_metrics_auth)):
        """Prometheus exposition format endpoint (Issue #55, #116, #123)."""
        return PlainTextResponse(
            container.metrics.generate_exposition(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/api/change-plan")
    def api_change_plan(authenticated: bool = Depends(check_dashboard_auth)):
        """Exposes the latest computed ChangePlan or generates a predictive dry-run plan (Issue #50)."""
        sync_state = container.snapshot()
        settings = get_settings()
        plan_obj = sync_state.get("_last_change_plan_obj")
        if plan_obj and hasattr(plan_obj, "summary"):
            return JSONResponse(serialize_change_plan(plan_obj))
        if (
            sync_state.get("last_change_plan")
            and isinstance(sync_state["last_change_plan"], dict)
            and "actions" in sync_state["last_change_plan"]
        ):
            return JSONResponse(sync_state["last_change_plan"])

        plan = compute_preview(
            settings,
            sync_state,
            container.discovery.discover,
            zone_id=sync_state.get("zone_id") or "preview-zone-id",
            existing_ingress=sync_state.get("_last_ingress") or [],
        )
        plan = container.cache_preview(plan)
        return JSONResponse(serialize_change_plan(plan))

    @app.post("/api/sync")
    async def api_sync(authenticated: bool = Depends(check_dashboard_auth)):
        sync_state = container.snapshot()
        await container.scheduler.run_sync()
        sync_state = container.snapshot()
        return JSONResponse({"message": "Sync triggered", "state": sanitize_sync_state(sync_state)})

    app.state.handlers = {
        "check_dashboard_auth": check_dashboard_auth,
        "check_metrics_auth": check_metrics_auth,
        "sanitize_sync_state": sanitize_sync_state,
        "api_sync": api_sync,
        "api_change_plan": api_change_plan,
        "get_prometheus_metrics": get_prometheus_metrics,
        "api_notifications_status": api_notifications_status,
        "api_history": api_history,
        "api_events": api_events,
        "api_status": api_status,
        "api_sync_preview": api_sync_preview,
        "get_dashboard": get_dashboard,
        "is_dashboard_enabled": is_dashboard_enabled,
        "ready": ready,
        "health": health,
    }
    return app


def create_app(settings=None, services=None):
    """Compose an independent ASGI application without starting background work."""
    from tunnel_sync.bootstrap import create_services
    from tunnel_sync.configuration.settings import Settings

    if services is None:
        services = create_services(settings if settings is not None else Settings(os.environ))
    return create_http_app(services)
