#!/bin/sh
# Installs one of the two timers. On the web machine: sudo infra/aws/install-timer.sh wake
#                                 On the worker machine: sudo infra/aws/install-timer.sh idle
set -eu
case "${1:-}" in
  wake) script=wake-worker.sh; every=1min; what="Start the worker machine when a job is due" ;;
  idle) script=stop-when-idle.sh; every=5min; what="Stop the worker machine after 15 idle minutes" ;;
  *) echo "usage: $0 wake|idle" >&2; exit 2 ;;
esac
cat > /etc/systemd/system/rehearsal-$1.service <<UNIT
[Unit]
Description=$what
After=docker.service
[Service]
Type=oneshot
ExecStart=/bin/sh /srv/rehearsal/infra/aws/$script
UNIT
cat > /etc/systemd/system/rehearsal-$1.timer <<UNIT
[Unit]
Description=$what (timer)
[Timer]
OnBootSec=2min
OnUnitActiveSec=$every
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now rehearsal-$1.timer
systemctl list-timers rehearsal-$1.timer --no-pager | head -3
