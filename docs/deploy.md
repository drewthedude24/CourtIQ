# Deploying CourtIQ to AWS

The API and detector run in Docker on one EC2 server. The database is PostgreSQL on Amazon
RDS, reachable only from that server. Everything is in `us-east-2` (Ohio).

```
Phone or laptop ──HTTP :80──► EC2 (Docker: FastAPI + detector, videos on its disk)
                                 │
                                 └──Postgres :5432 (private)──► RDS (sessions, shots)
```

These are the exact commands used. `<...>` marks values AWS gave back.

## 0. Before you start

- An AWS account and a monthly budget alert.
- The AWS CLI, signed in: `aws login --region us-east-2`.
- Docker Desktop.

## 1. Image registry (ECR)

```bash
aws ecr create-repository --repository-name courtiq --image-scanning-configuration scanOnPush=false
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-2.amazonaws.com
# EC2 is Intel (x86), the Mac is ARM, so build for the server's chip.
docker buildx build --platform linux/amd64 -t <account>.dkr.ecr.us-east-2.amazonaws.com/courtiq:latest --push .
```

## 2. Firewalls (security groups)

`courtiq-web` lets anyone reach the server on port 80. `courtiq-db` lets only servers in
`courtiq-web` reach Postgres. There is no SSH port: the server is reached with Session Manager.

```bash
aws ec2 create-security-group --group-name courtiq-web --description "CourtIQ server: HTTP from anywhere" --vpc-id <default vpc>
aws ec2 authorize-security-group-ingress --group-id <web sg> --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 create-security-group --group-name courtiq-db --description "CourtIQ database: Postgres from the server only" --vpc-id <default vpc>
aws ec2 authorize-security-group-ingress --group-id <db sg> --protocol tcp --port 5432 --source-group <web sg>
```

## 3. Database (RDS)

The password is random, stored encrypted in Parameter Store, and never typed or printed.

```bash
aws ssm put-parameter --name /courtiq/db-password --type SecureString --value "$(openssl rand -hex 24)"
aws rds create-db-instance --db-instance-identifier courtiq-db --engine postgres --engine-version 17.11 \
  --db-instance-class db.t4g.micro --allocated-storage 20 --storage-type gp3 --db-name courtiq \
  --master-username courtiq \
  --master-user-password "$(aws ssm get-parameter --name /courtiq/db-password --with-decryption --query Parameter.Value --output text)" \
  --vpc-security-group-ids <db sg> --no-publicly-accessible --backup-retention-period 1 --no-multi-az
```

The free plan allows at most 1 day of backups (7 was refused). The tables are created by the
app itself: `backend/database.py: initialize_database()` runs `db/schema.sql` at startup.

## 4. Server permissions (IAM role)

The server gets a role instead of stored keys. It can pull the image, read the one password
parameter, and accept Session Manager connections.

```bash
aws iam create-role --role-name courtiq-server --assume-role-policy-document file://ec2-trust.json
aws iam attach-role-policy --role-name courtiq-server --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
aws iam attach-role-policy --role-name courtiq-server --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name courtiq-server --policy-name read-db-password --policy-document file://read-db-password.json
aws iam create-instance-profile --instance-profile-name courtiq-server
aws iam add-role-to-instance-profile --instance-profile-name courtiq-server --role-name courtiq-server
```

`ec2-trust.json` lets EC2 use the role:

```json
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
```

`read-db-password.json` allows reading that one parameter and nothing else:

```json
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "ssm:GetParameter",
   "Resource": "arn:aws:ssm:us-east-2:<account>:parameter/courtiq/db-password"}]}
```

## 5. Server (EC2)

`c7i-flex.large`: 2 vCPUs, 4 GB, Intel. A 94 s clip peaked at 1.9 GB in Docker on the Mac and
longvid.mov at 0.9 GB on the server, so 4 GB is enough. `deploy/server-setup.sh` runs once at
first boot: it adds 2 GB of swap as a safety net, installs Docker, reads the database password
from Parameter Store, and starts the container with `--restart unless-stopped`.

```bash
sed -e 's/__ACCOUNT__/<account>/' -e 's/__DB_HOST__/<rds endpoint>/' deploy/server-setup.sh > user-data.sh
aws ec2 run-instances --image-id <Amazon Linux 2023 x86_64 AMI> --instance-type c7i-flex.large \
  --iam-instance-profile Name=courtiq-server --security-group-ids <web sg> \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=30,VolumeType=gp3}' \
  --metadata-options HttpTokens=required --user-data file://user-data.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=courtiq}]'
aws ec2 allocate-address --domain vpc
aws ec2 associate-address --instance-id <instance> --allocation-id <allocation>
```

The AMI id comes from
`aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`.
The app answered on `http://<elastic ip>/api/health` about 70 s after launch.

## 6. Shipping a new version

```bash
docker buildx build --platform linux/amd64 -t <account>.dkr.ecr.us-east-2.amazonaws.com/courtiq:latest --push .
python3 -c 'import json; print(json.dumps({"commands": [open("deploy/redeploy.sh").read()]}))' > redeploy.json
aws ssm send-command --instance-ids <instance> --document-name AWS-RunShellScript --parameters file://redeploy.json
```

`deploy/redeploy.sh` pulls the new image and replaces the container. Videos (on the server's
disk) and data (in RDS) are kept. To get a shell on the server, use Session Manager in the EC2
console ("Connect"). There is no SSH.

## Looking at the live database

RDS has no public address, so the Mac reaches it through a Session Manager tunnel via the server.
One-time setup: `brew install --cask session-manager-plugin`. The server must be running.

```bash
# Terminal 1: keep this open. Mac port 5433 now leads to RDS port 5432.
aws ssm start-session --target <instance> --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters host=<rds endpoint>,portNumber=5432,localPortNumber=5433

# Terminal 2: psql from the Postgres image. The password comes from Parameter Store, never typed.
PGPASSWORD="$(aws ssm get-parameter --name /courtiq/db-password --with-decryption --query Parameter.Value --output text)" \
  docker run --rm -it -e PGPASSWORD postgres:17 psql -h host.docker.internal -p 5433 -U courtiq courtiq
```

The pose keypoints are not in RDS, only the five form numbers per shot. Each session's joints
are in `/srv/courtiq/storage/results/<session id>/pose.jsonl` on the server's disk.

## 7. Saving credits

```bash
aws ec2 stop-instances --instance-ids <instance>     # site goes offline, server billing stops
aws ec2 start-instances --instance-ids <instance>    # app answered 14 s later, same address
aws rds stop-db-instance --db-instance-identifier courtiq-db   # AWS restarts it after 7 days
aws rds start-db-instance --db-instance-identifier courtiq-db
```

Changing the server size: stop it, then
`aws ec2 modify-instance-attribute --instance-id <instance> --instance-type '{"Value": "m7i-flex.large"}'`,
then start it. Stay on Intel sizes, since the image is built for x86.

List prices in us-east-2 (checked 2026-11-24):

| Piece | Price | Always on, per month |
|---|---|---|
| EC2 `c7i-flex.large` | $0.0848 / hour | $61.90 |
| RDS `db.t4g.micro` | $0.016 / hour | $11.68 |
| Elastic IP | $0.005 / hour | $3.65 |
| Server disk, 30 GB gp3 | $0.08 / GB-month | $2.40 |
| Database disk, 20 GB gp3 | $0.115 / GB-month | $2.30 |
| ECR, about 0.84 GB | $0.10 / GB-month | $0.08 |

With both EC2 and RDS stopped, about $8.50 a month remains (disks, IP, image).

## 8. Automatic deploys (GitHub Actions)

`.github/workflows/ci.yml` runs the tests and the frontend build on every push and pull
request. A push to `main` that passes also does section 6 by itself: build, push to ECR, run
`deploy/redeploy.sh` on the server, then check `/api/health`.

GitHub holds no AWS keys. With OIDC, GitHub signs a short token saying which repo and branch
the job is running for, and AWS swaps it for credentials that last one hour. Set up once:

```bash
aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com
aws iam create-role --role-name courtiq-github-deploy --assume-role-policy-document file://github-trust.json
aws iam put-role-policy --role-name courtiq-github-deploy --policy-name deploy --policy-document file://github-deploy.json
gh secret set AWS_ROLE_ARN --body 'arn:aws:iam::<account>:role/courtiq-github-deploy'
gh variable set EC2_INSTANCE_ID --body <instance>
```

`github-trust.json` lets only this repo's `main` branch use the role:

```json
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow",
   "Principal": {"Federated": "arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com"},
   "Action": "sts:AssumeRoleWithWebIdentity",
   "Condition": {"StringEquals": {
     "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
     "token.actions.githubusercontent.com:sub": "repo:drewthedude24@<owner id>/CourtIQ@<repo id>:ref:refs/heads/main"}}}]}
```

The two ids are GitHub's permanent numbers for the account and the repo. GitHub puts them in
the name it signs, so the plain `repo:drewthedude24/CourtIQ:...` is refused. The exact prefix
comes from `gh api repos/drewthedude24/CourtIQ/actions/oidc/customization/sub`.

`github-deploy.json` allows pushing to the one image repo and running a command on the one
server. Note that "a command" means any shell command, as root, on that server.

```json
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
  {"Effect": "Allow",
   "Action": ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
              "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage"],
   "Resource": "arn:aws:ecr:us-east-2:<account>:repository/courtiq"},
  {"Effect": "Allow", "Action": "ssm:SendCommand",
   "Resource": ["arn:aws:ec2:us-east-2:<account>:instance/<instance>",
                "arn:aws:ssm:us-east-2::document/AWS-RunShellScript"]},
  {"Effect": "Allow", "Action": "ssm:GetCommandInvocation", "Resource": "*"}]}
```

The deploy job fails if the server is stopped (section 7). The tests still run.

## Gotchas found while deploying

- **OpenVINO precision.** The server's CPU (Xeon 8488C) has AMX, and OpenVINO then runs in
  bfloat16 (16-bit floats) by default, which is faster. An earlier version forced 32-bit
  because 16-bit flipped one longvid shot. With the current pipeline 16-bit gets longvid
  6 of 6 and the six eval clips the same 60 of 63, so nothing is forced any more
  (`docs/speed-plan.md`, round 3).
- **Free plan limits.** RDS backups are capped at 1 day (7 was refused). Only some instance
  sizes are allowed (`aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true`).
- **Speed on 2 vCPUs.** Measured on the server on 2026-11-26 (`docs/speed-plan.md`, round 3):
  longvid.mov (47 s, 720p) takes about 50 s, the six eval clips run at 29.5 frames a second,
  and a real 1080p phone clip at about 24.6. The 2 vCPUs are two hyperthreads of one real
  core, so the server behaves like the laptop pinned to 1 CPU, not 2. It also slows down by
  about 10% after an hour of non-stop work. To time a job: upload it and read `total` and
  `frames` in `/srv/courtiq/storage/results/<session id>/timings.json`.
