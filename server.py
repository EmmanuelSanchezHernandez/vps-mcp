#!/usr/bin/env python3
"""VPS Infrastructure MCP Server — exposes Docker, nginx, systemd, and health tools over MCP (stdio).

Configuration (all optional, via environment):
  VPS_MCP_SERVICES   path to a JSON file {name: {"port": int|null, "path": str|null}} (default: the example below)
  VPS_MCP_PUBLIC_URL public URL used by health_check (default: none, external check skipped)
  VPS_MCP_NGINX_SITE nginx site file for nginx_config (default: /etc/nginx/sites-enabled/default)
  VPS_MCP_CONTAINER  default container for docker_logs / docker_restart
  VPS_MCP_PORTS      comma-separated ports shown by ports()
Every parameter that reaches a shell is validated or quoted: no tool accepts free-form commands.
"""

import functools
import json
import os
import re
import shlex
import subprocess

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vps-infra")

_EXAMPLE_SERVICES = {
    "app-web": {"port": 8001, "path": "/app/"},
    "api-gateway": {"port": 8002, "path": "/api/"},
    "worker": {"port": None, "path": None},
}


def _load_services():
    f = os.environ.get("VPS_MCP_SERVICES")
    if f:
        with open(f, encoding="utf-8") as h:
            return json.load(h)
    return _EXAMPLE_SERVICES


SERVICES = _load_services()
PUBLIC_URL = os.environ.get("VPS_MCP_PUBLIC_URL", "")
NGINX_SITE = os.environ.get("VPS_MCP_NGINX_SITE", "/etc/nginx/sites-enabled/default")
DEFAULT_CONTAINER = os.environ.get("VPS_MCP_CONTAINER", "app")
PORTS = os.environ.get("VPS_MCP_PORTS") or ",".join(str(s["port"]) for s in SERVICES.values() if s["port"])

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,99}$")
_SINCE = re.compile(r"^\d{1,4}[smhd]?$")


def _name(value: str) -> str:
    """Validate a unit/container name. Raises ValueError instead of building a shell string from it."""
    if not _NAME.match(value or ""):
        raise ValueError(f"invalid name: {value!r}")
    return value


def _since(value: str) -> str:
    if not _SINCE.match(value or ""):
        raise ValueError(f"invalid interval: {value!r}")
    return value


def _lines(value: int) -> int:
    return max(1, min(int(value), 1000))


def run(cmd: str, timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


def _safe(fn):
    """Turn validation errors into a tool result instead of a crash."""
    @functools.wraps(fn)   # keeps name, docstring and signature visible to FastMCP
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except ValueError as e:
            return f"REJECTED: {e}"
    return wrapper


@mcp.tool()
def docker_status() -> str:
    """List all Docker containers with name, status, ports, and image."""
    return run("docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}'")


@mcp.tool()
@_safe
def docker_logs(container: str = DEFAULT_CONTAINER, lines: int = 50, since: str = "30m") -> str:
    """Get recent Docker container logs."""
    return run(f"docker logs {_name(container)} --since {_since(since)} --tail {_lines(lines)} 2>&1", timeout=15)


@mcp.tool()
@_safe
def docker_restart(container: str = DEFAULT_CONTAINER) -> str:
    """Restart a Docker container."""
    return run(f"docker restart {_name(container)} 2>&1", timeout=30)


@mcp.tool()
def nginx_test() -> str:
    """Test nginx configuration syntax."""
    return run("nginx -t 2>&1")


@mcp.tool()
def nginx_config(section: str = "") -> str:
    """Show nginx config. Optionally filter by location/section keyword."""
    if section:
        return run(f"grep -B2 -A15 -F -e {shlex.quote(section)} {shlex.quote(NGINX_SITE)}")
    return run("nginx -T 2>&1 | head -200")


@mcp.tool()
def nginx_reload() -> str:
    """Test and reload nginx configuration."""
    test = run("nginx -t 2>&1")
    if "syntax is ok" in test and "test is successful" in test:
        reload_out = run("systemctl reload nginx 2>&1")
        return f"{test}\nReloaded: {reload_out or 'OK'}"
    return f"BLOCKED — config test failed:\n{test}"


@mcp.tool()
@_safe
def service_status(name: str = "") -> str:
    """Check systemd service status. If no name given, checks all configured services."""
    if name:
        return run(f"systemctl status {_name(name)} --no-pager -l 2>&1 | head -25")
    names = " ".join(_name(n) for n in SERVICES)
    return run(f"systemctl status {names} --no-pager -l 2>&1 | grep -E '(●|Active:|Main PID:)'")


@mcp.tool()
@_safe
def service_restart(name: str) -> str:
    """Restart a configured systemd service and verify it's active."""
    if name not in SERVICES:
        raise ValueError(f"{name!r} is not in the configured service list")
    run(f"systemctl restart {_name(name)} 2>&1")
    return run(f"systemctl is-active {_name(name)} 2>&1")


@mcp.tool()
@_safe
def service_logs(name: str, lines: int = 50, since: str = "30m") -> str:
    """Get recent journalctl logs for a systemd service."""
    return run(f"journalctl -u {_name(name)} --no-pager -n {_lines(lines)} --since '{_since(since)} ago' 2>&1", timeout=15)


@mcp.tool()
def health_check(service: str = "") -> str:
    """Run HTTP health checks on configured services. If no service specified, checks all."""
    targets = {}
    if service and service in SERVICES:
        if SERVICES[service]["port"]:
            targets[service] = SERVICES[service]["port"]
    else:
        for name, svc in SERVICES.items():
            if svc["port"]:
                targets[name] = svc["port"]
        if PUBLIC_URL:
            targets["public-url"] = "public"

    results = []
    for name, port in targets.items():
        if port == "public":
            code = run(f"curl -so /dev/null -w '%{{http_code}}' {shlex.quote(PUBLIC_URL)} --max-time 5")
        else:
            path = SERVICES.get(name, {}).get("path") or "/"
            code = run(f"curl -so /dev/null -w '%{{http_code}}' {shlex.quote(f'http://127.0.0.1:{int(port)}{path}')} --max-time 5")
        status = "OK" if code and code[0] in "234" else f"FAIL ({code})"
        results.append(f"{name}: {status}")
    return "\n".join(results)


@mcp.tool()
def ports() -> str:
    """Show listening TCP ports of the configured services."""
    wanted = "|".join(str(int(p)) for p in PORTS.split(",") if p.strip())
    return run(f"ss -tlnp | grep -E ':({wanted})'") if wanted else run("ss -tlnp")


@mcp.tool()
def disk_and_memory() -> str:
    """Show disk usage and memory status."""
    return run("df -h . && echo '---' && free -h")


@mcp.tool()
def ufw_status() -> str:
    """Show firewall (UFW) status and rules."""
    return run("ufw status verbose")


if __name__ == "__main__":
    mcp.run(transport="stdio")
