#!/usr/bin/env python3
"""
MotoServer Remote Bridge CLI & Client Library
Allows direct interaction with MotoServer over HTTPS/LAN without ADB.

Usage:
  python remote_bridge.py stats                  # Query live hardware telemetry
  python remote_bridge.py exec "ls -la /root"    # Execute bash command on MotoServer
  python remote_bridge.py read /root/dashboard/server.py 1 50  # Read file lines
  python remote_bridge.py prompt "Describe system status"      # Stream agent prompt
  python remote_bridge.py restart dashboard      # Restart PM2 service
"""

import sys
import os
import json
import urllib.request
import ssl
import argparse

MOTOSERVER_URL = os.environ.get("MOTOSERVER_HOST", "http://192.168.1.100:8080")
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DEFAULT_AGENT_KEY = os.environ.get("MOTOSERVER_AGENT_KEY", "YOUR_AGENT_API_KEY")


def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def query_stats(detailed=False):
    req = urllib.request.Request(
        f"{MOTOSERVER_URL}/api/stats",
        headers={"User-Agent": DEFAULT_UA}
    )
    with urllib.request.urlopen(req, context=get_ssl_context(), timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if not detailed:
            return {
                "uptime": data.get("uptime"),
                "battery": f"{data.get('battery_percent')}% ({data.get('battery_status')})",
                "cpu_temp": f"{data.get('cpu_temp')} °C",
                "cpu_usage": f"{data.get('cpu_usage')}%",
                "ram": f"{data.get('ram_used_mb')}/{data.get('ram_total_mb')} MB ({data.get('ram_percent')}%)",
                "pm2_dashboard": data.get("pm2_dashboard_alive"),
                "pm2_ttyd": data.get("pm2_ttyd_alive"),
                "ip": data.get("ip_address")
            }
        return data


def run_remote_command(command, timeout=35):
    prompt = f"Por favor ejecuta en bash con run_command: {command}"
    payload = json.dumps({
        "prompt": prompt,
        "conversation_id": "",
        "workspace": "/root/dashboard",
        "effort": "low"
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{MOTOSERVER_URL}/api/agent/stream",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_UA,
            "Authorization": f"Bearer {DEFAULT_AGENT_KEY}"
        }
    )

    output = []
    with urllib.request.urlopen(req, context=get_ssl_context(), timeout=timeout) as resp:
        for line in resp:
            t = line.decode("utf-8", errors="replace").strip()
            if t.startswith("data:"):
                raw = t[5:].strip()
                if raw == "[DONE]":
                    break
                try:
                    evt = json.loads(raw)
                    if evt.get("event") == "step_update":
                        delta = evt.get("step_update", {}).get("text_delta", "")
                        if delta:
                            output.append(delta)
                            sys.stdout.write(delta)
                            sys.stdout.flush()
                    elif evt.get("event") == "result":
                        res = evt.get("result", {}).get("response", "")
                        if res and not output:
                            output.append(res)
                            print(res)
                except Exception:
                    pass
    return "".join(output).strip()


def read_remote_file(file_path, start=1, max_lines=100):
    cmd = f"sed -n '{start},{start + max_lines - 1}p' {file_path}"
    return run_remote_command(cmd)


def restart_service(service="dashboard"):
    return run_remote_command(f"pm2 restart {service}")


def main():
    parser = argparse.ArgumentParser(description="MotoServer Remote Bridge CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # stats
    p_stats = subparsers.add_parser("stats", help="Query server stats")
    p_stats.add_argument("--detailed", "-d", action="store_true", help="Show full telemetry")

    # exec
    p_exec = subparsers.add_parser("exec", help="Execute bash command on MotoServer")
    p_exec.add_argument("cmd", help="Command to execute")
    p_exec.add_argument("--timeout", "-t", type=int, default=35, help="Timeout in seconds")

    # read
    p_read = subparsers.add_parser("read", help="Read remote file")
    p_read.add_argument("path", help="Path on MotoServer")
    p_read.add_argument("--start", "-s", type=int, default=1, help="Start line")
    p_read.add_argument("--lines", "-l", type=int, default=100, help="Number of lines")

    # restart
    p_restart = subparsers.add_parser("restart", help="Restart PM2 service")
    p_restart.add_argument("service", nargs="?", default="dashboard", help="Service name")

    args = parser.parse_args()

    if args.command == "stats":
        res = query_stats(detailed=args.detailed)
        print(json.dumps(res, indent=2))
    elif args.command == "exec":
        run_remote_command(args.cmd, timeout=args.timeout)
    elif args.command == "read":
        read_remote_file(args.path, start=args.start, max_lines=args.lines)
    elif args.command == "restart":
        restart_service(args.service)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
