#!/usr/bin/env python3
import os
import sys
import time
import socket

WAKELOCK_NAME = "MotoServer_Always_Awake"

def keep_kernel_awake():
    try:
        if os.path.exists('/sys/power/wake_lock'):
            with open('/sys/power/wake_lock', 'w') as f:
                f.write(WAKELOCK_NAME + "\n")
    except Exception as e:
        pass
    
    try:
        if os.path.exists('/sys/power/autosleep'):
            with open('/sys/power/autosleep', 'w') as f:
                f.write("off\n")
    except Exception as e:
        pass

def keep_cpus_online():
    for i in range(8):
        online_path = f"/sys/devices/system/cpu/cpu{i}/online"
        gov_path = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_governor"
        try:
            if os.path.exists(online_path):
                with open(online_path, 'w') as f:
                    f.write("1\n")
        except Exception:
            pass
        try:
            if os.path.exists(gov_path):
                with open(gov_path, 'w') as f:
                    f.write("performance\n")
        except Exception:
            pass

_cached_gateway = None
_failed_pings = 0

def keep_wifi_awake():
    global _cached_gateway, _failed_pings
    import subprocess
    if _cached_gateway is None:
        try:
            # Query all routing tables to locate default gateway dev wlan0
            res = subprocess.run(["nsenter", "-t", "1", "-m", "-n", "ip", "route", "show", "table", "all"], capture_output=True, text=True, timeout=2)
            for line in res.stdout.splitlines():
                if "default via" in line and "dev wlan0" in line:
                    _cached_gateway = line.split("via")[1].strip().split()[0]
                    break
        except:
            pass
            
    gateway = _cached_gateway or "192.168.1.254"
    ping_ok = False
    try:
        # Ping gateway and public DNS to force network hardware to stay awake
        p1 = subprocess.run(["ping", "-c", "1", "-W", "1", gateway], capture_output=True, timeout=2)
        p2 = subprocess.run(["ping", "-c", "1", "-W", "1", "1.1.1.1"], capture_output=True, timeout=2)
        if p1.returncode == 0 or p2.returncode == 0:
            ping_ok = True
    except:
        pass

    if ping_ok:
        _failed_pings = 0
    else:
        _failed_pings += 1
        if _failed_pings >= 60: # 60 failures * 5 seconds = 5 minutes
            print(f"⚠️ Network connection lost for 5 minutes. Logging connection issue...")
            _failed_pings = 0

def guard_battery_health():
    """Smart Battery Sentinel: Keeps battery between 55% and 80% to prevent swelling 24/7"""
    try:
        cap_path = "/sys/class/power_supply/battery/capacity"
        chg_path = "/sys/class/power_supply/battery/charging_enabled"
        if os.path.exists(cap_path) and os.path.exists(chg_path):
            with open(cap_path, 'r') as f:
                capacity = int(f.read().strip())
            with open(chg_path, 'r') as f:
                chg_enabled = f.read().strip()
                
            # If capacity >= 80% and charging is active -> Cut charge
            if capacity >= 80 and chg_enabled != "0":
                with open(chg_path, 'w') as f:
                    f.write("0\n")
                print(f"🔋 [Battery Guardian] Capacidad {capacity}% >= 80%. Carga cortada por seguridad térmica.")
            # If capacity <= 55% and charging is off -> Resume charge
            elif capacity <= 55 and chg_enabled != "1":
                with open(chg_path, 'w') as f:
                    f.write("1\n")
                print(f"⚡ [Battery Guardian] Capacidad {capacity}% <= 55%. Carga reactivada.")
    except Exception:
        pass

def apply_kernel_tunings():
    """Applies storage, network and CPU tunings on service startup"""
    import subprocess
    try:
        # 1. Flash I/O
        if os.path.exists("/sys/block/mmcblk0/queue/scheduler"):
            with open("/sys/block/mmcblk0/queue/scheduler", "w") as f:
                f.write("deadline\n")
        if os.path.exists("/sys/block/mmcblk0/queue/read_ahead_kb"):
            with open("/sys/block/mmcblk0/queue/read_ahead_kb", "w") as f:
                f.write("512\n")
                
        # 2. Network TCP Stack
        subprocess.run(["sysctl", "-w", "net.core.somaxconn=4096"], capture_output=True, timeout=2)
        subprocess.run(["sysctl", "-w", "net.ipv4.tcp_max_syn_backlog=4096"], capture_output=True, timeout=2)
        subprocess.run(["sysctl", "-w", "net.ipv4.tcp_tw_reuse=1"], capture_output=True, timeout=2)
        subprocess.run(["sysctl", "-w", "net.ipv4.tcp_fin_timeout=15"], capture_output=True, timeout=2)
        subprocess.run(["sysctl", "-w", "net.ipv4.tcp_fastopen=3"], capture_output=True, timeout=2)
        subprocess.run(["sysctl", "-w", "vm.swappiness=15"], capture_output=True, timeout=2)
        subprocess.run(["sysctl", "-w", "vm.vfs_cache_pressure=150"], capture_output=True, timeout=2)
    except Exception as e:
        print(f"⚠️ Error applying kernel tunings: {e}")

def main():
    print(f"🛡️ MotoServer Anti-Doze & Sentinel Service active.")
    print(f"🔒 Kernel Wakelock: '{WAKELOCK_NAME}' locked in /sys/power/wake_lock.")
    
    # Apply storage, memory and network tunings
    apply_kernel_tunings()
    
    # Forcefully disable Android Deep and Light Doze modes
    try:
        import subprocess
        res = subprocess.run(["nsenter", "-t", "1", "-m", "-n", "dumpsys", "deviceidle", "disable", "all"], capture_output=True, text=True, timeout=5)
        print(f"💤 Android Doze settings: {res.stdout.strip()}")
    except Exception as e:
        print(f"⚠️ Failed to disable Android Doze mode: {e}")

    loop_count = 0
    while True:
        keep_kernel_awake()
        keep_cpus_online()
        keep_wifi_awake()
        
        # Check battery health every 15 seconds (every 3 iterations)
        if loop_count % 3 == 0:
            guard_battery_health()
            
        loop_count += 1
        time.sleep(5)

if __name__ == "__main__":
    main()
