# MotoServer Development Agent MCP Server

This MCP server equips the AI agent with complete architectural mastery and remote control over MotoServer (Motorola Moto G5 Plus / Qualcomm Snapdragon 625 octa-core ARM64 running Kali Linux chroot under PM2 supervision).

## Guidelines & Best Practices

1. **Before modifying code or adding features:**
   - Use `motoserver_get_architecture` or `motoserver_inspect_component` to understand dependencies and file paths.
   - Use `motoserver_api_catalog` to inspect existing endpoints and avoid route naming conflicts.
   - Generate a plan with `motoserver_feature_blueprint` before large implementations.

2. **Reading code & verifying live state:**
   - Use `motoserver_read_remote_file` to inspect the exact lines of code on MotoServer.
   - Use `motoserver_server_health` to verify telemetry, PM2 process states, and system temperature.

3. **Applying modifications & deployments:**
   - ALWAYS use `motoserver_apply_patch_and_restart` rather than manual terminal commands when modifying code.
   - `motoserver_apply_patch_and_restart` automatically creates a timestamped `.bak` backup and compiles Python files (`python3 -m py_compile`) to ensure zero syntax errors before restarting PM2 services (`dashboard`).
   - If a syntax error is detected, the backup is automatically restored and the running service is kept alive.

4. **Hardware & Environment Constraints:**
   - **Snapdragon 625 (ARM64 Cortex-A53)**: Keep CPU load low; avoid synchronous blocking tasks on the main aiohttp thread.
   - **RAM (4GB total, ~2.2GB free)**: Stream large media/files rather than loading them in memory.
   - **Cloudflare CDN**: External requests to `https://your-domain.com` require `User-Agent: Mozilla/5.0`.
   - **Claude Desktop Theme**: All UI updates to `/root/dashboard/static/agent.html` must preserve Claude's warm dark palette (`#1b1917`, `#262422`, terracotta `#b55d3e`, stone `#3e3c38`).
