---
name: motoserver-dev
description: Specialized development agent and architectural expert for MotoServer (Motorola One XT1941-5 / Snapdragon 625 octa-core ARM64 running Kali Linux chroot under PM2). Use when developing new features, modifying server backend (aiohttp, security, notes, music), editing frontend PWAs (Claude Desktop styled agent, dashboard), inspecting telemetry, deploying code patches, or restarting PM2 services.
---

# MotoServer Development Agent Guide (`motoserver-dev`)

This skill guides the AI assistant in operating as a specialized software architect and developer for **MotoServer**. MotoServer is an autonomous, ultra-efficient server appliance running 24/7 on a physical **Motorola One (XT1941-5)** (Qualcomm Snapdragon 625 MSM8953 octa-core ARM64) inside a **Kali Linux chroot** environment supervised by **PM2**.

--------------------------------------------------------------------------------

## 1. System Architecture & Topology

### Physical Hardware & Specs
- **SoC:** Qualcomm Snapdragon 625 (MSM8953) @ 2.016 GHz (8x ARM Cortex-A53 64-bit).
- **GPU:** Qualcomm Adreno 506 (v1) @ 650 MHz.
- **Memory:** 4 GB LPDDR3 (3570 MB usable, ~60% free).
- **Swap:** 2048 MB zRAM / swapfile (~2-5% usage).
- **Storage:** 64 GB internal eMMC 5.1 + MicroSD card (`/sdcard` 51.3 GB total, 33.4 GB free).
- **Battery:** 3000 mAh Li-ion (monitored via `/sys/class/power_supply/battery`).
- **Thermals:** Monitored via `/sys/class/thermal/thermal_zone*` (CPU, PMIC, Chassis, Battery).
- **Torch:** Monitored/controlled via `/sys/class/leds/led:torch_0/brightness`.

### Operating System & Supervisor
- **Android Root Host:** Android 8.1/10 with root access.
- **Chroot Environment:** Kali Linux aarch64 in `/data/local/kali` mounted at `/`.
- **Kernel:** `Linux localhost 3.18.140-Mimir/38ba3905 #1 SMP PREEMPT aarch64`.
- **Process Supervisor:** `PM2 v7.0.4 God Daemon`.
  - Service `dashboard`: `python3 /root/dashboard/server.py` (CWD: `/root/dashboard`, Port: 8080).
  - Service `ttyd`: Web terminal on Port 7681.
- **Uptime Daemons:** `anti_doze.py` (Wakelock holder preventing Android CPU sleep when screen is off).

### Network & Security
- **Local Subnet:** IP `192.168.1.100` (Subnet: `192.168.1.0/24`). Dev PC IP: `192.168.1.50`.
- **Public Domain:** `https://your-domain.com` (Cloudflare CDN / Strict SSL).
- **Nginx Reverse Proxy:** Port 80 (redirects to 443) and Port 443 (SSL termination).
  - Reverse proxies `http://127.0.0.1:8080` for aiohttp API & UI.
  - Reverse proxies `http://127.0.0.1:7681` for ttyd terminal.
- **Cloudflare Requirement:** All outgoing client HTTP requests to `https://your-domain.com` **must** include the header `User-Agent: Mozilla/5.0` to avoid HTTP 403 Forbidden.

--------------------------------------------------------------------------------

## 2. Directory Tree & Codebase Map

All server code lives inside `/root/dashboard`:

```text
/root/dashboard/
├── server.py              # Main aiohttp web server, routing, stats, SSE agent bridge
├── security.py            # Session management, PIN auth, rate limiting, IP bans
├── cyber_suite.py         # Credentials vault, FIM, threat hunter, DEFCON security modes
├── notes_manager.py       # Notes CRUD, tagging, search, persistence in notes_data.json
├── music_manager.py       # YouTube Music search, streaming proxy, disk caching, P2P sync
├── music_admin.py         # Music admin catalog and metadata scraper
├── anti_doze.py           # Android wake lock manager for 24/7 background operation
├── sessions.json          # Active user sessions
├── notes_data.json        # Notes database
├── static/                # Web frontend assets
│   ├── index.html         # Main dashboard UI (gauges, stats, quick toggles)
│   ├── agent.html         # Claude Desktop styled PWA for Antigravity AI Agent
│   ├── agent-manifest.json# Web App Manifest for standalone PWA installation
│   ├── agent-sw.js        # Service Worker for cache management and offline handling
│   ├── music.html         # Web music player PWA
│   └── icons/             # App icons & SVGs
└── /root/.gemini/antigravity-cli/brain/  # AI Agent conversation folders & transcripts
```

--------------------------------------------------------------------------------

## 3. Dedicated MCP Development Tools

When the `motoserver-dev` MCP server is active, use the following specialized tools:

| Tool | Purpose | Key Arguments |
| :--- | :--- | :--- |
| `motoserver_get_architecture` | Returns the complete structural map across all layers | `layer`: `all`, `hardware`, `network`, `supervision`, `backend_modules`, `frontend_apps` |
| `motoserver_inspect_component` | Deep-dives into a specific component | `component`: `server_core`, `agent_ai`, `pwa_agent`, `telemetry_sensors`, `security_auth`, etc. |
| `motoserver_api_catalog` | Exhaustive table of all 60+ API endpoints | `category`: `all`, `system`, `actions`, `agent`, `files`, `notes`, `music`, `security` |
| `motoserver_server_health` | Live telemetry from `https://your-domain.com/api/stats` | `detailed`: boolean |
| `motoserver_feature_blueprint` | Architecture-grounded implementation planner | `feature_title`, `target_components`, `requirements` |
| `motoserver_read_remote_file` | Read files live on MotoServer with line slicing | `file_path`, `start_line`, `max_lines` |
| `motoserver_run_remote_command` | Execute shell commands on MotoServer Kali chroot | `command`, `timeout_seconds` |
| `motoserver_apply_patch_and_restart` | Safe patch applier with auto-backup, syntax check, and PM2 reload | `target_file`, `patch_type`, `search_content`, `replacement_content`, `restart_service` |

--------------------------------------------------------------------------------

## 4. Safe Deployment & Modification Runbook

To maintain 24/7 stability and prevent service downtime, always follow this workflow:

### Phase 1: Inspection & Blueprint
1. Check live health: `motoserver_server_health(detailed=false)`.
2. Inspect the relevant component: `motoserver_inspect_component(component="server_core")`.
3. Check the route catalog: `motoserver_api_catalog(category="...")`.
4. Read existing lines before editing: `motoserver_read_remote_file(file_path="...", start_line=..., max_lines=...)`.
5. Generate a blueprint: `motoserver_feature_blueprint(feature_title="...")`.

### Phase 2: Patch Application
Always use `motoserver_apply_patch_and_restart`:
```python
motoserver_apply_patch_and_restart(
    target_file="/root/dashboard/server.py",
    patch_type="replace_marker",
    search_content="marker_to_replace",
    replacement_content="new_code_with_marker",
    restart_service="dashboard"
)
```

**Why this is safe:**
1. **Timestamped Backup:** The tool creates `/root/dashboard/server.py.bak.<timestamp>` automatically before touching the file.
2. **Python Syntax Verification:** If editing a `.py` file, the tool runs `python3 -m py_compile` before restarting anything.
3. **Automatic Rollback:** If a syntax error is discovered, the backup is immediately restored and the live PM2 service is never interrupted.
4. **Service Reload:** If compilation succeeds, it executes `pm2 restart dashboard` and confirms it is online.

--------------------------------------------------------------------------------

## 5. Architectural Rules & Constraints

### 1. Hardware Constraints (Snapdragon 625)
- **Do not block the asyncio event loop:** Any CPU-heavy task (encryption, large file hashing, image conversion) must run in an executor thread or background worker (`loop.run_in_executor`).
- **Low Memory Overhead:** Keep RAM usage lean. Adhere to streaming (`StreamResponse`) for file downloads and audio instead of reading full files into memory buffers.
- **Thermal Awareness:** Normal operating temperature is 32°C - 38°C. If CPU temp exceeds 45°C, avoid triggering compute-heavy background tasks.

### 2. Frontend UI Styling (Claude Desktop Theme)
When updating `/root/dashboard/static/agent.html` or PWA elements, strictly adhere to Claude Desktop aesthetic tokens:
- **Background Main:** `#1b1917` (Deep stone black)
- **Sidebar Background:** `#262422` (Warm charcoal)
- **Primary Accent / Brand:** `#b55d3e` (Terracotta clay)
- **Hover & Surface Accent:** `#35322e` (Muted warm surface)
- **Border / Divider:** `#3e3c38` (Subtle stone border)
- **Text Primary:** `#ececec` (Clean neutral white)
- **Text Secondary / Muted:** `#9c9790` (Warm light gray)
- **Modals:** Use `z-index: 99999`, backdrop blur, `Escape` key dismiss, and clear confirmation actions.

### 3. PWA & Service Worker Rules
- When updating HTML/CSS/JS in `static/`, update the cache version string in `agent-sw.js` (e.g. `v3`, `v4`) or ensure unregister fallback is active so users immediately receive new code without stale Service Worker cache locks.
