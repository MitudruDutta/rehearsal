#!/bin/sh
# Starts the worker machine when a job is due. Runs every minute on the web machine (rehearsal-wake.timer).
set -eu
. /etc/rehearsal-worker.env # WORKER_ID, AWS_REGION
cd /srv/rehearsal
set -- $(docker compose -f infra/compose.full.yaml --env-file infra/deploy.env exec -T api python - < infra/aws/queue_state.py)
[ "${1:-0}" -gt 0 ] || exit 0
state=$(aws ec2 describe-instances --region "$AWS_REGION" --instance-ids "$WORKER_ID" --query 'Reservations[0].Instances[0].State.Name' --output text)
if [ "$state" = stopped ]; then
  logger -t rehearsal-wake "$1 job(s) due: starting the worker machine"
  aws ec2 start-instances --region "$AWS_REGION" --instance-ids "$WORKER_ID" > /dev/null
fi
