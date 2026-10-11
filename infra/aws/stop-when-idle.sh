#!/bin/sh
# Stops the worker machine after 15 idle minutes: three checks in a row, 5 minutes apart, with no job due and none
# running. Runs on the worker machine (rehearsal-idle.timer). The web machine starts it again when a job is due.
# To keep it on (maintenance): sudo systemctl stop rehearsal-idle.timer
set -eu
[ "$(cut -d. -f1 /proc/uptime)" -ge 900 ] || exit 0 # never in the first 15 minutes after boot
cd /srv/rehearsal
set -- $(docker compose -f infra/compose.full.yaml --env-file infra/deploy.env exec -T worker python - < infra/aws/queue_state.py) || exit 0
count=/run/rehearsal-idle-count
if [ "${1:-1}" -eq 0 ] && [ "${2:-1}" -eq 0 ]; then
  n=$(( $(cat "$count" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$count"
  if [ "$n" -ge 3 ]; then
    logger -t rehearsal-idle "no jobs for 15 minutes: stopping the worker machine"
    shutdown -h now
  fi
else
  echo 0 > "$count"
fi
