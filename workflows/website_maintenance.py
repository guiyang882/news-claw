"""Check or explicitly reload the website's Nginx and Gunicorn layers."""

import argparse
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess


class LocalHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except OSError:
            raw.close()
            raise


def settings(config):
    value = config["workflow"]["website_runtime"]
    if value["proxy"] != "nginx" or value["content_update_action"] != "none":
        raise ValueError("Nginx content publication must not restart services")
    for key in ("application_service", "proxy_service"):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.@-]*\.service", value[key]):
            raise ValueError("Invalid website service name")
    for key in ("application_reload_command", "proxy_validate_command", "proxy_reload_command"):
        command = value[key]
        if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg for arg in command):
            raise ValueError("Maintenance commands must be argument arrays")
    health = value["health"]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}", health["host"]):
        raise ValueError("Invalid HTTPS health hostname")
    if not health["path"].startswith("/") or any(char in health["path"] for char in "\r\n"):
        raise ValueError("Invalid health path")
    for key in ("application_port", "https_port"):
        if type(health[key]) is not int or not 1 <= health[key] <= 65535:
            raise ValueError("Invalid local health port")
    for value_, maximum in ((health["timeout_seconds"], 30), (value["command_timeout_seconds"], 120)):
        if type(value_) is not int or not 1 <= value_ <= maximum:
            raise ValueError("Invalid maintenance timeout")
    return value


def command(argv, timeout):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise RuntimeError(f"{' '.join(argv)} failed ({result.returncode}): {detail}")


def health_probe(config):
    health = config["health"]
    results = {}
    for layer in ("application", "nginx"):
        connection = (http.client.HTTPConnection("127.0.0.1", health["application_port"], timeout=health["timeout_seconds"])
                      if layer == "application" else LocalHTTPS(health["host"], health["https_port"], timeout=health["timeout_seconds"]))
        try:
            connection.request("GET", health["path"], headers={"Host": health["host"]})
            response = connection.getresponse()
            body = response.read(16385)
            if response.status != 200 or len(body) > 16384:
                raise RuntimeError(f"{layer} health check failed: HTTP {response.status}")
            payload = json.loads(body)
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise RuntimeError(f"{layer} returned an invalid health result")
            server = response.getheader("Server", "")
            if layer == "nginx" and "nginx" not in server.lower():
                raise RuntimeError("HTTPS listener is not the configured Nginx ingress")
            results[layer] = {"status": response.status, "server": server}
        finally:
            connection.close()
    return results


def run(config, action, *, execute=False, invoke=command, probe=health_probe):
    value = settings(config)
    commands = {
        "check": [],
        "reload-application": [value["application_reload_command"]],
        "reload-proxy": [value["proxy_reload_command"]],
    }
    if action not in commands:
        raise ValueError("Unknown website maintenance action")
    if action != "check" and not execute:
        return {"success": True, "business_status": "preview", "action": action,
                "commands": [value["proxy_validate_command"], *commands[action]]}
    timeout = value["command_timeout_seconds"]
    invoke(["systemctl", "is-active", "--quiet", value["application_service"], value["proxy_service"]], timeout)
    invoke(value["proxy_validate_command"], timeout)
    before = probe(value)
    for argv in commands[action]:
        invoke(argv, timeout)
    after = probe(value) if commands[action] else before
    return {"success": True, "business_status": "healthy" if action == "check" else "reloaded",
            "action": action, "checks": after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-config", type=Path, default=os.environ.get("NEWS_CLAW_TASK_CONFIG_PATH"))
    parser.add_argument("--action", choices=("check", "reload-application", "reload-proxy"), default="check")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.task_config is None:
        parser.error("Provide --task-config or the Go engine's task configuration snapshot")
    try:
        config = json.loads(args.task_config.read_text())
        result = run(config, args.action, execute=args.execute)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, http.client.HTTPException, subprocess.SubprocessError) as error:
        result = {"success": False, "business_status": "failed", "action": args.action, "error": str(error)}
    if destination := os.environ.get("NEWS_CLAW_RESULT_PATH"):
        from .daily_blog import atomic_json
        atomic_json(Path(destination), result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
