#!/bin/bash
while true; do
    if ! pgrep -f "python3 server.py" > /dev/null; then
        echo "[$(date)] server.py caído, reiniciando automáticamente..." >> /root/dashboard/watchdog.log
        cd /root/dashboard && python3 server.py >> /root/dashboard/server.log 2>&1 &
    fi
    sleep 3
done
