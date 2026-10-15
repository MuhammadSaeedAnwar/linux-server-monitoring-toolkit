"""Human-readable text rendering for CLI output.

JSON output (``--json``) is produced directly from the same dictionaries,
so these functions only decide how things look in a terminal.
"""

from __future__ import annotations

from typing import Any


def _status(value: Any) -> str:
    return f"[{str(value or 'unknown').upper():<8}]"


def _fmt_uptime(seconds: Any) -> str:
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "n/a"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _fmt_num(value: Any, suffix: str = "", digits: int = 1) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def _system_lines(system: dict[str, Any]) -> list[str]:
    lines = [
        f"System   {_status(system.get('status'))}",
        (
            f"  CPU {_fmt_num(system.get('cpu_percent'), '%')}"
            f"   Memory {_fmt_num(system.get('memory_percent'), '%')}"
            f"   Disk {_fmt_num(system.get('disk_percent'), '%')}"
        ),
        (
            f"  Load {_fmt_num(system.get('load_average_1m'), digits=2)}"
            f" / {_fmt_num(system.get('load_average_5m'), digits=2)}"
            f" / {_fmt_num(system.get('load_average_15m'), digits=2)}"
            f"   Uptime {_fmt_uptime(system.get('uptime_seconds'))}"
        ),
    ]
    for warning in system.get("warnings") or []:
        lines.append(f"  ! {warning}")
    return lines


def _service_lines(services: list[dict[str, Any]]) -> list[str]:
    lines = ["Services"]
    if not services:
        lines.append("  (none configured)")
    width = max((len(str(s.get("name", ""))) for s in services), default=0)
    for s in services:
        lines.append(f"  {_status(s.get('status'))} {s.get('name', '')!s:<{width}}  {s.get('detail', '')}")
    return lines


def _network_lines(results: list[dict[str, Any]]) -> list[str]:
    lines = ["Network"]
    if not results:
        lines.append("  (none configured)")
    type_w = max((len(str(r.get("check_type", ""))) for r in results), default=0)
    target_w = max((len(str(r.get("target", ""))) for r in results), default=0)
    for r in results:
        latency = r.get("latency_ms")
        latency_txt = f"{float(latency):7.1f} ms" if latency is not None else "      -   "
        lines.append(
            f"  {_status(r.get('status'))} {r.get('check_type', '')!s:<{type_w}}  "
            f"{r.get('target', '')!s:<{target_w}}  {latency_txt}  {r.get('detail', '')}"
        )
    return lines


def format_check_text(output: dict[str, Any]) -> str:
    """Render the result of ``toolkit check`` for a terminal."""
    sections: list[list[str]] = []
    if "system" in output:
        sections.append(_system_lines(output["system"]))
    if "services" in output:
        sections.append(_service_lines(output["services"]))
    if "network" in output:
        sections.append(_network_lines(output["network"]))

    footer = [f"Alerts raised: {output.get('alert_count', 0)}"]
    storage = output.get("storage")
    if storage:
        footer.append(f"Storage: {storage}")
    sections.append(footer)
    return "\n\n".join("\n".join(section) for section in sections)


def format_alerts_text(rows: list[dict[str, Any]]) -> str:
    """Render stored alerts (newest first) for a terminal."""
    if not rows:
        return "No alerts stored."
    lines = []
    for row in rows:
        raised = row.get("raised_at")
        raised_txt = raised.isoformat() if hasattr(raised, "isoformat") else str(raised)
        lines.append(f"{raised_txt}  {_status(row.get('severity'))} {row.get('source', '')}: {row.get('message', '')}")
    return "\n".join(lines)
