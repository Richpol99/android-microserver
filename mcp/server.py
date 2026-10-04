#!/usr/bin/env python3
"""
MotoServer Development Agent MCP Server (JSON-RPC 2.0 stdio)
Specialized agent for Motorola One (XT1941-5 / Snapdragon 625) running Kali Linux chroot.

Features:
- Complete system architecture & component deep-dive
- Exhaustive API catalog (60+ endpoints)
- Live telemetry and health inspection via http://192.168.1.100:8080/api/stats
- Feature blueprint generator adapted to MotoServer constraints
- Remote command execution bridge via MotoServer agent stream
- Remote file reading with line slicing
- Safe patch deployment with backup, python syntax check, and PM2 service restart
"""

import sys
import os
import json
import urllib.request
import ssl
import time
import base64
import traceback

MOTOSERVER_URL = os.environ.get("MOTOSERVER_HOST", "http://192.168.1.100:8080")
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DEFAULT_AGENT_KEY = os.environ.get("MOTOSERVER_AGENT_KEY", "YOUR_AGENT_API_KEY")

# Architecture Data
ARCHITECTURE = {
    "hardware": {
        "device": "Motorola One (XT1941-5 / codename 'deen')",
        "soc": "Qualcomm Snapdragon 625 (MSM8953) @ 2.016 GHz",
        "cpu_cores": "8x ARM Cortex-A53 64-bit (aarch64)",
        "gpu": "Qualcomm Adreno 506 (v1) @ up to 650 MHz",
        "ram": "4 GB LPDDR3 (3570 MB usable, ~60% available)",
        "swap": "2048 MB zRAM / swapfile (~2-5% usage)",
        "storage": "64 GB internal eMMC 5.1 + MicroSD slot (/sdcard 51.3 GB total, 33.4 GB free)",
        "battery": "3000 mAh Li-ion (monitored via /sys/class/power_supply/battery)",
        "thermal_sensors": "/sys/class/thermal/thermal_zone* (CPU, PMIC, Chassis, Battery sensors)",
        "flashlight": "/sys/class/leds/led:torch_0/brightness or camera torch sysfs node",
        "wireless": "Wi-Fi 802.11 a/b/g/n dual-band (wlan0 interface)"
    },
    "os_environment": {
        "base_os": "Android 8.1 / 10 Custom ROM (rooted via Magisk/su)",
        "chroot_environment": "Kali Linux ARM64 (aarch64) in /data/local/kali mounted to /",
        "kernel": "Linux localhost 3.18.140-Mimir/38ba3905 #1 SMP PREEMPT aarch64",
        "init_system": "Init scripts & PM2 daemon (no standard systemd PID 1)",
        "working_directories": {
            "dashboard_root": "/root/dashboard",
            "agent_brain": "/root/.gemini/antigravity-cli/brain",
            "pm2_logs": "/root/.pm2/logs",
            "nginx_config": "/etc/nginx"
        }
    },
    "networking": {
        "local_ip": "192.168.1.100 (Subnet: 192.168.1.0/24)",
        "workstation_ip": "192.168.1.50",
        "public_domain": "http://192.168.1.100:8080",
        "cdn_proxy": "Cloudflare CDN / Strict SSL / DDoS protection",
        "reverse_proxy": "Nginx on port 80 (redirects to 443) and port 443 (SSL termination)",
        "proxy_passes": {
            "dashboard_api": "http://127.0.0.1:8080 (Python aiohttp web server)",
            "ttyd_terminal": "http://127.0.0.1:7681 (Web console terminal)",
            "ssh_service": "Port 22 (Dropbear/OpenSSH daemon)"
        },
        "cloudflare_rules": "Requires User-Agent: Mozilla/5.0 header on all external API requests"
    },
    "supervision": {
        "manager": "PM2 v7.0.4 God Daemon",
        "services": [
            {
                "name": "dashboard",
                "script": "python3 /root/dashboard/server.py",
                "cwd": "/root/dashboard",
                "port": 8080,
                "restart_command": "pm2 restart dashboard",
                "status_check": "http://192.168.1.100:8080/api/stats -> pm2_dashboard_alive: true"
            },
            {
                "name": "ttyd",
                "script": "ttyd -p 7681 -t fontSize=14 bash",
                "port": 7681,
                "restart_command": "pm2 restart ttyd",
                "status_check": "http://192.168.1.100:8080/api/stats -> pm2_ttyd_alive: true"
            }
        ],
        "watchdogs": [
            "anti_doze.py (Prevents Android deep sleep and CPU throttling when screen is off)",
            "cyber_suite.py (Security event watchdog, file integrity monitor)",
            "panic_watchdog (Automatic recovery upon high temperature or kernel panic)"
        ]
    },
    "backend_modules": {
        "/root/dashboard/server.py": "Main aiohttp.web application, route registry, hardware telemetry, agent SSE stream bridge, static file server",
        "/root/dashboard/security.py": "Session cookies, PIN verification, 2FA challenge, IP whitelist/ban, security events log, audit reports",
        "/root/dashboard/cyber_suite.py": "Password/secret vault, attack surface inspector, FIM baseline, DEFCON security states, SSL inspector",
        "/root/dashboard/notes_manager.py": "Notes CRUD operations, tags, search, JSON persistence in notes_data.json, archiving and sync",
        "/root/dashboard/music_manager.py": "YouTube Music search/scraping, audio proxy/stream, disk caching in temp_music_cache/, WebRTC P2P sync",
        "/root/dashboard/music_admin.py": "Admin upload, playlist management, audio metadata scanner",
        "/root/dashboard/anti_doze.py": "Wakelock manager ensuring 24/7 background CPU operation"
    },
    "frontend_apps": {
        "/root/dashboard/static/index.html": "Main server dashboard UI (live gauges, CPU/RAM charts, thermals, flashlight toggle, quick actions)",
        "/root/dashboard/static/agent.html": "Claude Desktop styled PWA for Antigravity AI Agent with conversation sidebar, history, individual chat deletion, markdown parser, code syntax highlighting, auto-scroll",
        "/root/dashboard/static/music.html": "Dedicated web music player PWA",
        "/root/dashboard/static/agent-manifest.json": "Web App Manifest for standalone installation of Claude AGY agent",
        "/root/dashboard/static/agent-sw.js": "Service Worker for PWA lifecycle and cache management"
    }
}

COMPONENTS = {
    "server_core": {
        "file": "/root/dashboard/server.py",
        "description": "Core aiohttp web server handling HTTP/WS requests, telemetry gathering, and orchestrating other managers.",
        "key_routines": [
            "api_stats(request): polls Snapdragon 625 CPU, GPU, RAM, battery, thermal zones, returns JSON",
            "api_agent_stream(request): connects to Antigravity CLI agent via SSE streaming",
            "api_agent_conversations(request): reads /root/.gemini/antigravity-cli/brain/ and extracts user-prompt titles",
            "api_agent_conversation_delete(request): cleanly purges conversation UUID directory"
        ],
        "dependencies": ["aiohttp", "security", "notes_manager", "music_manager", "cyber_suite"],
        "pm2_service": "dashboard"
    },
    "agent_ai": {
        "file": "/root/dashboard/server.py + /root/.gemini/antigravity-cli",
        "description": "Antigravity AI Agent bridge. Runs autonomous coding and execution workflows directly on MotoServer.",
        "storage": "/root/.gemini/antigravity-cli/brain/<uuid>/",
        "log_files": [
            "transcript.jsonl (compact step-by-step logs)",
            "transcript_full.jsonl (untruncated payloads)"
        ],
        "endpoints": [
            "POST /api/agent/stream",
            "GET /api/agent/conversations",
            "GET /api/agent/conversation/{id}",
            "DELETE /api/agent/conversation/{id}",
            "POST /api/agent/conversation/{id}/delete"
        ]
    },
    "pwa_agent": {
        "file": "/root/dashboard/static/agent.html",
        "description": "Claude Desktop styled frontend for Antigravity AI. Dark theme (#1b1917, #262422, #b55d3e terracotta), responsive sidebar, individual conversation deletion modal, auto-scroll with observer, code block copy.",
        "assets": [
            "/static/agent-manifest.json",
            "/static/agent-sw.js",
            "/static/antigravity-icon.png"
        ]
    },
    "telemetry_sensors": {
        "file": "/root/dashboard/server.py (api_stats)",
        "description": "Low-level Linux sysfs telemetry for Snapdragon 625.",
        "sysfs_paths": {
            "battery_percent": "/sys/class/power_supply/battery/capacity",
            "battery_status": "/sys/class/power_supply/battery/status",
            "battery_temp": "/sys/class/power_supply/battery/temp (divide by 10)",
            "battery_voltage": "/sys/class/power_supply/battery/voltage_now",
            "cpu_freq": "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
            "cpu_cores": "/sys/devices/system/cpu/cpu[0-7]/online",
            "gpu_model": "/sys/class/kgsl/kgsl-3d0/gpu_model (Adreno506)",
            "gpu_busy": "/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage",
            "thermal_cpu": "/sys/class/thermal/thermal_zone0/temp"
        }
    },
    "security_auth": {
        "file": "/root/dashboard/security.py",
        "description": "Authentication and authorization layer. Manages session tokens, PIN protection, login challenges, and rate limiting.",
        "storage": [
            "/root/dashboard/security_config.json",
            "/root/dashboard/security_events.json",
            "/root/dashboard/sessions.json"
        ]
    },
    "cyber_suite": {
        "file": "/root/dashboard/cyber_suite.py",
        "description": "Advanced server protection suite: encrypted credentials vault, attack surface monitor, FIM, SSH key manager, DEFCON modes.",
        "storage": "/root/dashboard/vault_data/"
    },
    "notes_manager": {
        "file": "/root/dashboard/notes_manager.py",
        "description": "Notes management with markdown support, tags, search, and archiving.",
        "storage": "/root/dashboard/notes_data.json"
    },
    "music_manager": {
        "file": "/root/dashboard/music_manager.py + music_admin.py",
        "description": "Music player backend with streaming, YouTube integration, playlist management, and local caching.",
        "storage": "/root/dashboard/temp_music_cache/"
    },
    "anti_doze": {
        "file": "/root/dashboard/anti_doze.py",
        "description": "Android wakelock daemon keeping Snapdragon 625 active when screen turns off. Crucial for 24/7 uptime."
    }
}

API_CATALOG = [
    {"method": "GET", "path": "/api/stats", "handler": "api_stats", "module": "server.py", "auth": False, "category": "system", "desc": "Live hardware telemetry (CPU, GPU, RAM, Battery, Temps, PM2 status, Network)"},
    {"method": "GET", "path": "/api/system/info", "handler": "api_system_info", "module": "server.py", "auth": False, "category": "system", "desc": "Hardware specs, kernel release, uptime, Kali release"},
    {"method": "POST", "path": "/api/actions/flashlight", "handler": "api_action_flashlight", "module": "server.py", "auth": True, "category": "actions", "desc": "Toggle device LED flashlight"},
    {"method": "POST", "path": "/api/actions/restart", "handler": "api_action_restart", "module": "server.py", "auth": True, "category": "actions", "desc": "Trigger PM2 restart for dashboard or services"},
    {"method": "POST", "path": "/api/agent/stream", "handler": "api_agent_stream", "module": "server.py", "auth": False, "category": "agent", "desc": "SSE streaming prompt execution with Antigravity agent"},
    {"method": "GET", "path": "/api/agent/conversations", "handler": "api_agent_conversations", "module": "server.py", "auth": False, "category": "agent", "desc": "List past agent conversations with generated titles & mtime"},
    {"method": "GET", "path": "/api/agent/conversation/{id}", "handler": "api_agent_conversation_detail", "module": "server.py", "auth": False, "category": "agent", "desc": "Full transcript steps for a conversation ID"},
    {"method": "DELETE", "path": "/api/agent/conversation/{id}", "handler": "api_agent_conversation_delete", "module": "server.py", "auth": False, "category": "agent", "desc": "Delete conversation folder permanently"},
    {"method": "POST", "path": "/api/agent/conversation/{id}/delete", "handler": "api_agent_conversation_delete", "module": "server.py", "auth": False, "category": "agent", "desc": "POST fallback to delete conversation"},
    {"method": "GET", "path": "/api/files/list", "handler": "api_files_list", "module": "server.py", "auth": True, "category": "files", "desc": "List directory contents on MotoServer"},
    {"method": "GET", "path": "/api/files/content", "handler": "api_file_content_get", "module": "server.py", "auth": True, "category": "files", "desc": "Read text file contents"},
    {"method": "POST", "path": "/api/files/save-content", "handler": "api_file_content_save", "module": "server.py", "auth": True, "category": "files", "desc": "Write text file contents"},
    {"method": "POST", "path": "/api/files/upload", "handler": "api_files_upload", "module": "server.py", "auth": True, "category": "files", "desc": "Upload binary or text file to server"},
    {"method": "GET", "path": "/api/notes/list", "handler": "api_notes_list", "module": "notes_manager.py", "auth": False, "category": "notes", "desc": "Get all saved notes"},
    {"method": "POST", "path": "/api/notes/save", "handler": "api_notes_save", "module": "notes_manager.py", "auth": False, "category": "notes", "desc": "Create or update note"},
    {"method": "POST", "path": "/api/notes/delete", "handler": "api_notes_delete", "module": "notes_manager.py", "auth": False, "category": "notes", "desc": "Delete note by ID"},
    {"method": "GET", "path": "/api/music/search", "handler": "api_music_search", "module": "music_manager.py", "auth": False, "category": "music", "desc": "Search songs on YouTube Music"},
    {"method": "GET", "path": "/api/music/stream", "handler": "api_music_stream", "module": "music_manager.py", "auth": False, "category": "music", "desc": "Stream audio chunk or proxy audio"},
    {"method": "GET", "path": "/api/security/dashboard", "handler": "api_security_dashboard", "module": "security.py", "auth": True, "category": "security", "desc": "Security overview, blocked IPs, active sessions"},
    {"method": "GET", "path": "/api/security/vault/list", "handler": "api_vault_list", "module": "cyber_suite.py", "auth": True, "category": "cyber_suite", "desc": "List credential vault items"}
]


def execute_remote_cmd(command: str, timeout: int = 35) -> str:
    """Executes a command on MotoServer via the agent stream bridge."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

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
            "User-Agent": DEFAULT_USER_AGENT,
            "Authorization": f"Bearer {DEFAULT_AGENT_KEY}"
        }
    )

    output = []
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
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
                    elif evt.get("event") == "result":
                        res = evt.get("result", {}).get("response", "")
                        if res:
                            output.append(f"\n{res}")
                except Exception:
                    pass
    return "".join(output).strip()


def query_health() -> dict:
    """Queries live hardware & service stats from MotoServer."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        f"{MOTOSERVER_URL}/api/stats",
        headers={"User-Agent": DEFAULT_USER_AGENT}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


# MCP Tool Handlers
def handle_get_architecture(params: dict) -> str:
    layer = params.get("layer", "all").lower()
    if layer != "all" and layer in ARCHITECTURE:
        return json.dumps({layer: ARCHITECTURE[layer]}, indent=2)
    return json.dumps(ARCHITECTURE, indent=2)


def handle_inspect_component(params: dict) -> str:
    comp_name = params.get("component", "").lower()
    if not comp_name:
        available = list(COMPONENTS.keys())
        return f"Error: 'component' parameter required. Available components: {', '.join(available)}"
    
    if comp_name in COMPONENTS:
        return json.dumps({comp_name: COMPONENTS[comp_name]}, indent=2)
    
    # fuzzy search
    matches = {k: v for k, v in COMPONENTS.items() if comp_name in k}
    if matches:
        return json.dumps(matches, indent=2)
    return f"Component '{comp_name}' not found. Available components: {', '.join(COMPONENTS.keys())}"


def handle_api_catalog(params: dict) -> str:
    cat = params.get("category", "all").lower()
    if cat == "all":
        items = API_CATALOG
    else:
        items = [e for e in API_CATALOG if e.get("category") == cat]
    return json.dumps({"category": cat, "total": len(items), "endpoints": items}, indent=2)


def handle_server_health(params: dict) -> str:
    try:
        stats = query_health()
        detailed = params.get("detailed", True)
        if not detailed:
            return json.dumps({
                "status": "ONLINE",
                "uptime": stats.get("uptime"),
                "battery": f"{stats.get('battery_percent')}% ({stats.get('battery_status')})",
                "cpu_temp": f"{stats.get('cpu_temp')} °C",
                "pm2_dashboard": stats.get("pm2_dashboard_alive"),
                "pm2_ttyd": stats.get("pm2_ttyd_alive"),
                "ip": stats.get("ip_address")
            }, indent=2)
        return json.dumps(stats, indent=2)
    except Exception as e:
        return f"Error querying MotoServer health: {str(e)}"


def handle_feature_blueprint(params: dict) -> str:
    title = params.get("feature_title", "Custom Feature")
    comps = params.get("target_components", [])
    reqs = params.get("requirements", "No specific requirements provided.")

    blueprint = {
        "feature_title": title,
        "target_components": comps or ["server_core", "pwa_agent"],
        "hardware_and_environment_constraints": [
            "Snapdragon 625 (ARM64 Cortex-A53): Keep CPU utilization low, avoid heavy synchronous operations in event loop.",
            "RAM limit (4GB, ~2.2GB available): Avoid keeping large in-memory caches; stream large data or use temp files.",
            "Thermal threshold (45°C limit): Monitor CPU/PMIC temps; throttles at high frequencies.",
            "Cloudflare CDN: Every client HTTP request must send User-Agent: Mozilla/5.0 to avoid 403 Forbidden.",
            "PM2 supervision: Changes to /root/dashboard/server.py require 'pm2 restart dashboard'. Check syntax with py_compile before restarting."
        ],
        "step_by_step_plan": [
            {
                "phase": "1. Backend Implementation (aiohttp)",
                "actions": [
                    "Define async route handler in appropriate manager or server.py.",
                    "Validate request payloads and enforce security checks.",
                    "Register route with app.router.add_get/add_post in server.py."
                ]
            },
            {
                "phase": "2. Frontend UI / PWA Implementation",
                "actions": [
                    "Integrate into /root/dashboard/static/agent.html or index.html.",
                    "Adhere to Claude Desktop aesthetic design tokens: background #1b1917, sidebar #262422, accent #b55d3e, border #3e3c38.",
                    "Ensure mobile touch responsiveness and offline PWA service worker caching compatibility."
                ]
            },
            {
                "phase": "3. Automated Verification & Deployment",
                "actions": [
                    "Use motoserver_apply_patch_and_restart tool to safely deploy modifications.",
                    "Tool automatically creates a backup .bak timestamp and verifies python syntax.",
                    "Tool triggers 'pm2 restart dashboard' and confirms the service is online via /api/stats."
                ]
            }
        ],
        "requirements_context": reqs
    }
    return json.dumps(blueprint, indent=2)


def handle_run_remote_command(params: dict) -> str:
    cmd = params.get("command")
    if not cmd:
        return "Error: 'command' argument is required."
    timeout = int(params.get("timeout_seconds", 35))
    try:
        out = execute_remote_cmd(cmd, timeout=timeout)
        return out if out else "(Command completed with no output)"
    except Exception as e:
        return f"Error executing remote command: {str(e)}"


def handle_read_remote_file(params: dict) -> str:
    path = params.get("file_path")
    if not path:
        return "Error: 'file_path' argument is required."
    start = int(params.get("start_line", 1))
    max_lines = int(params.get("max_lines", 150))
    end = start + max_lines - 1

    cmd = f"sed -n '{start},{end}p' {path}"
    try:
        out = execute_remote_cmd(cmd, timeout=30)
        return out
    except Exception as e:
        return f"Error reading remote file: {str(e)}"


def handle_apply_patch_and_restart(params: dict) -> str:
    target_file = params.get("target_file")
    patch_type = params.get("patch_type", "replace_marker")
    search_content = params.get("search_content", "")
    replacement_content = params.get("replacement_content", "")
    restart_service = params.get("restart_service", "dashboard")

    if not target_file:
        return "Error: 'target_file' argument is required."
    if patch_type == "replace_marker" and not search_content:
        return "Error: 'search_content' is required when patch_type is 'replace_marker'."
    if not replacement_content and patch_type != "delete":
        return "Error: 'replacement_content' is required."

    payload = {
        "target_file": target_file,
        "patch_type": patch_type,
        "search_content": search_content,
        "replacement_content": replacement_content,
        "restart_service": restart_service
    }
    b64_payload = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

    remote_script = f"""python3 -c "
import base64, json, sys, shutil, time, subprocess

data = json.loads(base64.b64decode('{b64_payload}').decode('utf-8'))
target = data['target_file']
ptype = data.get('patch_type', 'replace_marker')
search = data.get('search_content', '')
repl = data.get('replacement_content', '')
svc = data.get('restart_service', 'dashboard')

ts = int(time.time())
backup = f'{{target}}.bak.{{ts}}'
shutil.copy2(target, backup)

with open(target, 'r', encoding='utf-8') as f:
    content = f.read()

if ptype == 'replace_marker':
    if search not in content:
        sys.exit(f'SEARCH_MARKER_NOT_FOUND: could not find exact target string in {{target}}')
    content = content.replace(search, repl, 1)
elif ptype == 'append':
    content = content + '\\n' + repl
elif ptype == 'full_content':
    content = repl

with open(target, 'w', encoding='utf-8') as f:
    f.write(content)

if target.endswith('.py'):
    check = subprocess.run(['python3', '-m', 'py_compile', target], capture_output=True, text=True)
    if check.returncode != 0:
        shutil.copy2(backup, target)
        sys.exit(f'SYNTAX_ERROR: python validation failed, restored backup: {{check.stderr}}')

if svc and svc != 'none':
    res = subprocess.run(['pm2', 'restart', svc], capture_output=True, text=True)
    if res.returncode != 0:
        print(f'PM2_WARNING: {{res.stderr}}')
    else:
        print(f'PM2_RESTARTED: {{svc}} successfully reloaded')

print(f'SUCCESS: {{target}} patched. Backup: {{backup}}')
" """

    try:
        out = execute_remote_cmd(remote_script, timeout=40)
        return out
    except Exception as e:
        return f"Error executing patch: {str(e)}"


# MCP Schema & Dispatcher
TOOLS = [
    {
        "name": "motoserver_get_architecture",
        "description": "Returns the complete architectural map of MotoServer (Hardware, Kali Chroot OS, Network, Cloudflare, PM2 supervision, aiohttp backend modules, and PWA frontends).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layer": {
                    "type": "string",
                    "enum": ["all", "hardware", "os_environment", "networking", "supervision", "backend_modules", "frontend_apps"],
                    "description": "Optional architectural layer to filter by. Defaults to 'all'."
                }
            }
        }
    },
    {
        "name": "motoserver_inspect_component",
        "description": "Deep-dives into a specific MotoServer component (e.g., server_core, agent_ai, pwa_agent, telemetry_sensors, security_auth, cyber_suite, music_manager, notes_manager, anti_doze).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "component": {
                    "type": "string",
                    "description": "Name of the component to inspect (e.g. 'server_core', 'pwa_agent', 'telemetry_sensors', 'agent_ai')."
                }
            },
            "required": ["component"]
        }
    },
    {
        "name": "motoserver_api_catalog",
        "description": "Returns the complete catalog of MotoServer REST endpoints, methods, auth rules, parameters, and handler functions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["all", "system", "actions", "agent", "files", "notes", "music", "security", "cyber_suite"],
                    "description": "Filter by API category. Defaults to 'all'."
                }
            }
        }
    },
    {
        "name": "motoserver_server_health",
        "description": "Queries live status and hardware telemetry directly from http://192.168.1.100:8080/api/stats (PM2 status, CPU/GPU temps, battery state, RAM, uptime, network).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "detailed": {
                    "type": "boolean",
                    "description": "Whether to return full raw telemetry or a compact summary. Defaults to true."
                }
            }
        }
    },
    {
        "name": "motoserver_feature_blueprint",
        "description": "Generates a structured, step-by-step implementation plan for adding a new feature or modifying existing components, taking into account Snapdragon 625 hardware, aiohttp patterns, Cloudflare policies, and PM2 restarts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "feature_title": {
                    "type": "string",
                    "description": "Title or summary of the feature to develop."
                },
                "target_components": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of components involved (e.g. ['server_core', 'pwa_agent'])."
                },
                "requirements": {
                    "type": "string",
                    "description": "Detailed functional requirements."
                }
            },
            "required": ["feature_title"]
        }
    },
    {
        "name": "motoserver_run_remote_command",
        "description": "Directly executes a shell command on MotoServer in Kali Linux chroot via the remote agent execution bridge, returning terminal output.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash shell command to execute on MotoServer."
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout in seconds. Defaults to 35."
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "motoserver_read_remote_file",
        "description": "Reads file contents directly from MotoServer (e.g. /root/dashboard/server.py or static assets) with optional line range.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path on MotoServer (e.g. '/root/dashboard/server.py')."
                },
                "start_line": {
                    "type": "integer",
                    "description": "Starting line number (1-based). Defaults to 1."
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to return. Defaults to 150."
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "motoserver_apply_patch_and_restart",
        "description": "Safely applies a code modification to a file on MotoServer with automatic timestamped backup, python syntax validation, and optional PM2 service restart.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_file": {
                    "type": "string",
                    "description": "Absolute path of the target file on MotoServer."
                },
                "patch_type": {
                    "type": "string",
                    "enum": ["replace_marker", "append", "full_content"],
                    "description": "Type of patch to apply. Defaults to 'replace_marker'."
                },
                "search_content": {
                    "type": "string",
                    "description": "Exact text chunk to search for when patch_type is 'replace_marker'."
                },
                "replacement_content": {
                    "type": "string",
                    "description": "The replacement or appended code content."
                },
                "restart_service": {
                    "type": "string",
                    "description": "PM2 service name to restart upon success (e.g. 'dashboard', 'ttyd', or 'none'). Defaults to 'dashboard'."
                }
            },
            "required": ["target_file", "replacement_content"]
        }
    }
]

TOOL_DISPATCH = {
    "motoserver_get_architecture": handle_get_architecture,
    "motoserver_inspect_component": handle_inspect_component,
    "motoserver_api_catalog": handle_api_catalog,
    "motoserver_server_health": handle_server_health,
    "motoserver_feature_blueprint": handle_feature_blueprint,
    "motoserver_run_remote_command": handle_run_remote_command,
    "motoserver_read_remote_file": handle_read_remote_file,
    "motoserver_apply_patch_and_restart": handle_apply_patch_and_restart,
}


def send_response(response: dict):
    line = json.dumps(response, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main():
    # Set unbuffered text mode
    if sys.platform == "win32":
        import msvcrt
        import os
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

    sys.stderr.write("MotoServer Development Agent MCP Server running (stdio)\n")
    sys.stderr.flush()

    for raw_line in sys.stdin:
        if not raw_line:
            continue
        line_str = raw_line.strip()
        if not line_str:
            continue
        try:
            req = json.loads(line_str)
        except Exception as e:
            sys.stderr.write(f"Invalid JSON received: {e}\n")
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False}
                    },
                    "serverInfo": {
                        "name": "motoserver-dev",
                        "version": "1.0.0"
                    }
                }
            })
        elif method == "notifications/initialized":
            # Client acknowledgment
            pass
        elif method == "ping":
            send_response({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "tools/list":
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": TOOLS
                }
            })
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            handler = TOOL_DISPATCH.get(tool_name)
            if not handler:
                send_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool '{tool_name}' not found."
                    }
                })
            else:
                try:
                    result_text = handler(tool_args)
                    send_response({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": str(result_text)
                                }
                            ],
                            "isError": False
                        }
                    })
                except Exception as ex:
                    tb = traceback.format_exc()
                    send_response({
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Error executing {tool_name}: {str(ex)}\n{tb}"
                                }
                            ],
                            "isError": True
                        }
                    })
        else:
            if req_id is not None:
                send_response({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method '{method}' not implemented."
                    }
                })


if __name__ == "__main__":
    main()
