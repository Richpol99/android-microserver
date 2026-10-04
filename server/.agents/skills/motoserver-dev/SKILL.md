---
name: motoserver-dev
description: Specialized development agent and architectural expert for MotoServer (Motorola Moto G5 Plus / Snapdragon 625 octa-core ARM64 running Kali Linux chroot under PM2). Use when developing new features, modifying server backend (aiohttp, security, notes, music), editing frontend PWAs (Claude Desktop styled agent, dashboard), inspecting telemetry, deploying code patches, or restarting PM2 services.
---

# MotoServer Development Agent Guide ()

This skill guides the AI assistant in operating as a specialized software architect and developer for **MotoServer**. MotoServer is an autonomous, ultra-efficient server appliance running 24/7 on a physical **Motorola Moto G5 Plus** (Qualcomm Snapdragon 625 MSM8953 octa-core ARM64) inside a **Kali Linux chroot** environment supervised by **PM2**.

-------------------------------------------------------------------------------

## 1. System Architecture & Topology

### Physical Hardware & Specs
- **SoC:** Qualcomm Snapdragon 625 (MSM8953) @ 2.016 GHz (8x ARM Cortex-A53 64-bit).
- **GPU:** Qualcomm Adreno 506 (v1) @ 650 MHz.
- **Memory:** 4 GB LPDDR3 (3570 MB usable, ~60% free).
- **Swap:** 2048 MB zRAM / swapfile (~2-5% usage).
- **Storage:** 64 GB internal eMMC 5.1 + MicroSD card ( 51.3 GB total, 33.4 GB free).
- **Battery:** 3000 mAh Li-Ion (monitored via ).
- **Thermals:** Monitored via  (CPU, PMIC, Chassis, Battery).
- **Torch:** Monitored/controlled via .

### Operating System & Supervisor
- **Android Root Host:** Android 8.1/10 with root access.
- **Chroot Environment:** Kali Linux aarch64 in  mounted at .
- **Kernel:** .
- **Process Supervisor:** .
  - Service : 🚀 MotoServer Backend running on http://0.0.0.0:8080
⏰ MotoServer Reminder Daemon Started (CWD: , Port: 8080).
  - Service : Web terminal on Port 7681.
- **Uptime Daemons:**  (Wakelock holder preventing Android CPU sleep when screen is off).

### Network & Security
- **Local Subnet:** IP  (Subnet: ). Dev PC IP: .
- **Public Domain:**  (Cloudflare CDN / Strict SSL).
- **Nginx Reverse Proxy:** Port 80 (redirects to 443) and Port 443 (SSL termination).
  - Reverse proxies  for aiohttp API & UI.
  - Reverse proxies  for ttyd terminal.
- **Cloudflare Requirement:** All outgoing client HTTP requests to  **must** include the header  to avoid HTTP 403 Forbidden.

-------------------------------------------------------------------------------

## 2. Directory Tree & Codebase Map

All server code lives inside :



-------------------------------------------------------------------------------

## 3. Dedicated MCP Development Tools

When the  MCP server is active, use the following specialized tools:

| Tool | Purpose | Key Arguments |
| :--- | :--- | :--- |
|  | Returns the complete structural map across all layers | : , , , , ,  |
|  | Deep-dives into a specific component | : , , , , , etc. |
|  | Exhaustive table of all 60+ API endpoints | : , , , , , , ,  |
|  | Live telemetry from  | : boolean |
|  | Architecture-grounded implementation planner | , ,  |
|  | Read files live on MotoServer with line slicing | , ,  |
|  | Execute shell commands on MotoServer Kali chroot | ,  |
|  | Safe patch applier with auto-backup, syntax check, and PM2 reload | , , , ,  |

-------------------------------------------------------------------------------

## 4. Safe Deployment & Modification Runbook

To maintain 24/7 stability and prevent service downtime, always follow this workflow:

### Phase 1: Inspection & Blueprint
1. Check live health: .
2. Inspect the relevant component: .
3. Check the route catalog: .
4. Read existing lines before editing: .
5. Generate a blueprint: .

### Phase 2: Patch Application
Always use :


**Why this is safe:**
1. **Timestamped Backup:** The tool creates  automatically before touching the file.
2. **Python Syntax Verification:** If editing a  file, the tool runs  before restarting anything.
3. **Automatic Rollback:** If a syntax error is discovered, the backup is immediately restored and the live PM2 service is never interrupted.
4. **Service Reload:** If compilation succeeds, it executes  and confirms it is online.

-------------------------------------------------------------------------------

## 5. Architectural Rules & Constraints

### 1. Hardware Constraints (Snapdragon 625)
- **Do not block the asyncio event loop:** Any CPU-heavy task (encryption, large file hashing, image conversion) must run in an executor thread or background worker ().
- **Low Memory Overhead:** Keep RAM usage lean. Adhere to streaming () for file downloads and audio instead of reading full files into memory buffers.
- **Thermal Awareness:** Normal operating temperature is 32 C - 38 C. If CPU temp exceeds 45 C, avoid triggering compute-heavy background tasks.

### 2. Frontend UI Styling (Claude Desktop Theme)
When updating  or PWA elements, strictly adhere to Claude Desktop aesthetic tokens:
- **Background Main:**  (Deep stone black)
- **Sidebar Background:**  (Warm charcoal)
- **Primary Accent / Brand:**  (Terracotta clay)
- **Hover & Surface Accent:**  (Muted warm surface)
- **Border / Divider:**  (Subtle stone border)
- **Text Primary:**  (Clean neutral white)
- **Text Secondary / Muted:**  (Warm light gray)
- **Modals:** Use , backdrop blur,  key dismiss, and clear confirmation actions.

### 3. PWA & Service Worker Rules
- When updating HTML/CSS/JS in , update the cache version string in  (e.g. , ) or ensure unregister fallback is active so users immediately receive new code without stale Service Worker cache locks.
