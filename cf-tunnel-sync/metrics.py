"""Native Prometheus metrics registry and text exposition format generator."""

import threading
from typing import Dict, Tuple


class PrometheusRegistry:
    """Thread-safe in-memory metrics registry producing Prometheus exposition format."""

    def __init__(self):
        self._lock = threading.Lock()
        # Counters: (name, label_tuple) -> value
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        # Gauges: (name, label_tuple) -> value
        self._gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        # Help strings: name -> help text
        self._help: Dict[str, str] = {}
        # Type strings: name -> metric type (counter/gauge)
        self._types: Dict[str, str] = {}

        # Register default metrics
        self.register("cf_tunnel_sync_runs_total", "counter", "Total count of synchronization loop runs")
        self.register(
            "cf_tunnel_sync_duration_seconds", "gauge", "Duration in seconds of the most recent sync execution"
        )
        self.register("cf_tunnel_services_discovered", "gauge", "Number of valid Docker services currently discovered")
        self.register(
            "cf_tunnel_safety_guard_tripped",
            "gauge",
            "1 if blast-radius safety deletion guard is currently tripped, 0 otherwise",
        )
        self.register("cf_tunnel_api_requests_total", "counter", "Total Cloudflare API HTTP requests executed")

        # Initialize defaults
        self.set_gauge("cf_tunnel_safety_guard_tripped", 0.0)
        self.set_gauge("cf_tunnel_services_discovered", 0.0)
        self.set_gauge("cf_tunnel_sync_duration_seconds", 0.0)

    def register(self, name: str, metric_type: str, help_text: str):
        with self._lock:
            self._help[name] = help_text
            self._types[name] = metric_type

    def _labels_to_key(self, labels: Dict[str, str]) -> Tuple[Tuple[str, str], ...]:
        return tuple(sorted(labels.items()))

    def inc_counter(self, name: str, value: float = 1.0, labels: Dict[str, str] = None):
        key = self._labels_to_key(labels or {})
        with self._lock:
            self._counters[(name, key)] = self._counters.get((name, key), 0.0) + value

    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        key = self._labels_to_key(labels or {})
        with self._lock:
            self._gauges[(name, key)] = float(value)

    def inc_gauge(self, name: str, value: float = 1.0, labels: Dict[str, str] = None):
        key = self._labels_to_key(labels or {})
        with self._lock:
            self._gauges[(name, key)] = self._gauges.get((name, key), 0.0) + value

    def dec_gauge(self, name: str, value: float = 1.0, labels: Dict[str, str] = None):
        key = self._labels_to_key(labels or {})
        with self._lock:
            self._gauges[(name, key)] = self._gauges.get((name, key), 0.0) - value

    def record_sync_run(
        self, duration: float, status: str = "success", discovered_count: int = 0, safety_tripped: bool = False
    ):
        """Convenience method to record a completed sync run."""
        self.inc_counter("cf_tunnel_sync_runs_total", 1.0, {"status": status})
        self.set_gauge("cf_tunnel_sync_duration_seconds", duration)
        self.set_gauge("cf_tunnel_services_discovered", float(discovered_count))
        self.set_gauge("cf_tunnel_safety_guard_tripped", 1.0 if safety_tripped else 0.0)

    def generate_exposition(self) -> str:
        """Render metrics into standard Prometheus text exposition format (version 0.0.4)."""
        lines = []
        with self._lock:
            all_names = sorted(
                set(list(self._help.keys()) + [n for n, _ in self._counters] + [n for n, _ in self._gauges])
            )
            for name in all_names:
                help_text = self._help.get(name, f"Metric {name}")
                metric_type = self._types.get(name, "untyped")
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {metric_type}")

                # Output counters matching name
                found_entries = False
                for (metric_name, label_tuple), val in sorted(self._counters.items()):
                    if metric_name == name:
                        found_entries = True
                        if label_tuple:
                            label_str = ",".join(f'{k}="{v}"' for k, v in label_tuple)
                            lines.append(f"{name}{{{label_str}}} {val}")
                        else:
                            lines.append(f"{name} {val}")

                # Output gauges matching name
                for (metric_name, label_tuple), val in sorted(self._gauges.items()):
                    if metric_name == name:
                        found_entries = True
                        if label_tuple:
                            label_str = ",".join(f'{k}="{v}"' for k, v in label_tuple)
                            lines.append(f"{name}{{{label_str}}} {val}")
                        else:
                            lines.append(f"{name} {val}")

                if not found_entries:
                    # Provide default zero if never populated
                    lines.append(f"{name} 0")

        return "\n".join(lines) + "\n"


# Global singleton registry
metrics_registry = PrometheusRegistry()
