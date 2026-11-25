#!/bin/bash
# Run on the EC2 server (as root) to swap in the newest image from ECR.
# Videos stay in /srv/courtiq/storage and data stays in RDS, so nothing is lost.
set -euo pipefail

REGION=us-east-2
REGISTRY=$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$REGION.amazonaws.com
DATABASE_URL=$(docker inspect courtiq --format '{{range .Config.Env}}{{println .}}{{end}}' | grep ^DATABASE_URL=)

aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REGISTRY
docker pull $REGISTRY/courtiq:latest
docker rm -f courtiq
docker run -d --name courtiq --restart unless-stopped -p 80:8000 \
  -e "$DATABASE_URL" \
  -v /srv/courtiq/storage:/app/storage \
  $REGISTRY/courtiq:latest
docker image prune -f
