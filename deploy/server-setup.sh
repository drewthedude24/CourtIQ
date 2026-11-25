#!/bin/bash
# Runs once, as root, the first time the EC2 server boots (EC2 "user data").
# Installs Docker, then starts the CourtIQ container. Docker restarts it after every reboot.
set -euo pipefail

REGION=us-east-2
REGISTRY=__ACCOUNT__.dkr.ecr.$REGION.amazonaws.com
DB_HOST=__DB_HOST__

# 2 GB of disk as backup memory. A long clip peaked at 1.9 GB of the server's 4 GB, so this is
# only a safety net against the detector being killed mid-video.
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo "/swapfile swap swap defaults 0 0" >> /etc/fstab

dnf install -y docker
systemctl enable --now docker

# The server's IAM role allows both of these. No keys are stored on the server.
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REGISTRY
DB_PASSWORD=$(aws ssm get-parameter --region $REGION --name /courtiq/db-password \
  --with-decryption --query Parameter.Value --output text)

# Uploads and annotated videos live on the server's disk, outside the container.
mkdir -p /srv/courtiq/storage
docker run -d --name courtiq --restart unless-stopped -p 80:8000 \
  -e DATABASE_URL="postgresql://courtiq:$DB_PASSWORD@$DB_HOST:5432/courtiq" \
  -v /srv/courtiq/storage:/app/storage \
  $REGISTRY/courtiq:latest
