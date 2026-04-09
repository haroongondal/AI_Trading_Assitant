# Cloud Provisioning Automation

This directory contains SDK-based provisioning helpers for the deployment model documented in `backend/docs/AWS_ZERO_COST_DEPLOYMENT.md`.

**After you provision two EC2 instances (API + Ollama on AWS),** use [README_AWS_TWO_INSTANCES.md](README_AWS_TWO_INSTANCES.md) for on-instance setup. **AWS CLI discovery** (status, SSM command lines, backend SG id): run `scripts/aws_tasks.sh` from this directory.

## What These Scripts Automate

### AWS

`scripts/provision_aws_backend.py` creates or reuses:

- an EC2 IAM role with `AmazonSSMManagedInstanceCore`
- an EC2 instance profile
- a least-privilege backend security group that opens only `80` and `443`
- a single EC2 instance for the backend

`scripts/provision_aws_ollama.py` creates or reuses:

- a separate IAM role and instance profile for the Ollama host (SSM)
- a security group that allows TCP `11434` only from your **backend** security group and/or a VPC CIDR you choose
- a single EC2 instance with cloud-init that installs and starts Ollama

Use this when you want **both** the API and Ollama on AWS (same VPC). Point the backend `OLLAMA_BASE_URL` at `http://<ollama-private-ip>:11434`.

### OCI

`scripts/provision_oci_ollama.py` creates or reuses:

- a VCN
- an internet gateway
- a route table
- a security list that opens only SSH publicly
- a subnet
- a single OCI Compute instance for Ollama

## What These Scripts Do Not Fully Automate

Some steps still require portal work or interactive auth:

- creating the AWS account itself
- creating the OCI tenancy itself
- adding billing verification to cloud accounts
- Tailscale login and device approval
- DuckDNS hostname setup
- running Certbot against your real domain
- cloning the backend repo onto the EC2 instance
- editing the backend `.env` with your real values
- optional Google OAuth setup in Google Cloud Console

## Directory Layout

```text
backend/deploy/
  README.md
  requirements.txt
  config/
    aws-backend.example.json
    aws-ollama.example.json
    oci-ollama.example.json
  scripts/
    provision_aws_backend.py
    provision_aws_ollama.py
    provision_oci_ollama.py
  templates/
    aws-user-data.sh
    aws-ollama-user-data.sh
    oci-cloud-init.sh
```

## Install Dependencies

Create a small dedicated Python environment for provisioning:

```bash
cd backend/deploy
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Secrets And Credentials

These scripts now read cloud credentials from environment variables, not from AWS CLI profiles or `~/.oci/config`.

The easiest setup is:

```bash
cd backend/deploy
cp .env.example .env
```

Then edit `backend/deploy/.env`.

The scripts automatically load that file before talking to AWS or OCI.

## AWS Credential Setup

The AWS provisioner reads standard boto3 environment variables:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_SESSION_TOKEN` if you use temporary credentials

You can run it from:

- your local machine with exported env vars
- AWS CloudShell
- any machine where those environment variables are already set

### Create a dedicated AWS provisioning IAM user

Only do this if you do not already have a better-administered platform identity.

In AWS Console:

1. Open `IAM`.
2. Create a user for programmatic access.
3. Generate an access key.
4. Store the access key and secret key safely.

Then put them into `backend/deploy/.env`:

```env
AWS_ACCESS_KEY_ID=REPLACE_ME
AWS_SECRET_ACCESS_KEY=REPLACE_ME
# AWS_SESSION_TOKEN=REPLACE_ME
```

### AWS permissions required by the provisioning principal

The provisioning principal needs enough permission to create and inspect:

- EC2 instances
- security groups
- subnets and VPC metadata
- IAM roles and instance profiles
- SSM public parameter reads for the Ubuntu AMI

If you want a starting policy for a dedicated provisioning principal, this is a reasonable broad bootstrap policy for this project:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:CreateTags",
        "ec2:CreateSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:DescribeImages",
        "ec2:DescribeInstances",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeSubnets",
        "ec2:RunInstances",
        "ec2:DescribeVpcs",
        "iam:AttachRolePolicy",
        "iam:AddRoleToInstanceProfile",
        "iam:CreateInstanceProfile",
        "iam:CreateRole",
        "iam:GetInstanceProfile",
        "iam:GetRole",
        "iam:PassRole",
        "ssm:GetParameter",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

For a real production organization, tighten this further around specific role names, instance profile names, regions, and tagging conditions.

## OCI Credential Setup

The OCI script reads its auth material from environment variables.

### 1. Create an OCI API signing key pair

On your local machine:

```bash
mkdir -p ~/.oci
openssl genrsa -out ~/.oci/oci_api_key.pem 2048
openssl rsa -pubout -in ~/.oci/oci_api_key.pem -out ~/.oci/oci_api_key_public.pem
chmod 600 ~/.oci/oci_api_key.pem
```

### 2. Upload the public key in OCI Console

In OCI Console:

1. Open your user profile.
2. Go to `API Keys`.
3. Click `Add API Key`.
4. Upload `~/.oci/oci_api_key_public.pem`.
5. Copy the displayed `user`, `fingerprint`, and tenancy information.

### 3. Put the OCI values into `backend/deploy/.env`

Use either a key file path or inline private key content.

Example using a file path:

```env
OCI_USER_OCID=ocid1.user.oc1..REPLACE_ME
OCI_FINGERPRINT=REPLACE_ME
OCI_TENANCY_OCID=ocid1.tenancy.oc1..REPLACE_ME
OCI_REGION=us-ashburn-1
OCI_PRIVATE_KEY_PATH=/absolute/path/to/oci_api_key.pem
```

Example using inline private key content:

```env
OCI_USER_OCID=ocid1.user.oc1..REPLACE_ME
OCI_FINGERPRINT=REPLACE_ME
OCI_TENANCY_OCID=ocid1.tenancy.oc1..REPLACE_ME
OCI_REGION=us-ashburn-1
OCI_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\nREPLACE_ME\n-----END PRIVATE KEY-----
```

If the private key is encrypted, also set:

```env
OCI_PRIVATE_KEY_PASSPHRASE=REPLACE_ME
```

### 4. Create OCI IAM policies

In OCI you usually grant permissions through policy statements attached to groups.

Create a group for the provisioning user, then add policy statements like:

```text
Allow group AiTradingProvisioners to manage virtual-network-family in compartment <your_compartment_name>
Allow group AiTradingProvisioners to manage instance-family in compartment <your_compartment_name>
Allow group AiTradingProvisioners to manage volume-family in compartment <your_compartment_name>
Allow group AiTradingProvisioners to inspect compartments in tenancy
Allow group AiTradingProvisioners to read app-catalog-listing in tenancy
Allow group AiTradingProvisioners to read app-catalog-listing-content in tenancy
```

If your organization uses a stricter OCI IAM model, align these statements with your compartment boundaries.

## Manual Inputs You Must Gather First

Before running the scripts, collect:

### AWS

- target region
- subnet ID in a VPC where the EC2 backend should live
- your chosen instance name
- if you use `provision_aws_ollama.py`: the **backend** security group ID (`sg-...`) from the API instance, and optionally your VPC CIDR for `ollama_ingress_cidr`

### OCI

- compartment OCID
- desired OCI region
- an SSH public key path such as `~/.ssh/id_ed25519.pub`

Generate an SSH key if you do not have one:

```bash
ssh-keygen -t ed25519 -C "ai-trading-oci"
```

## Prepare The Config Files

Copy the examples:

```bash
cd backend/deploy
cp .env.example .env
cp config/aws-backend.example.json config/aws-backend.json
cp config/aws-ollama.example.json config/aws-ollama.json
cp config/oci-ollama.example.json config/oci-ollama.json
```

Then edit both `.env` and the JSON config files.

### Important AWS config fields

- `region`: AWS region for the EC2 backend
- `subnet_id`: required, the script uses this to derive the VPC
- `instance_name`: Name tag for the backend instance
- `user_data_path`: optional bootstrap shell script

### Important AWS Ollama config fields (`config/aws-ollama.json`)

- `subnet_id`: use the **same VPC** as the backend (can be a private subnet if the backend reaches it)
- `backend_security_group_id`: the API instance security group; Ollama accepts port `11434` only from this group (recommended)
- `ollama_ingress_cidr`: optional extra CIDR (for example your VPC `10.0.0.0/16`) if you need broader in-VPC access
- `instance_type`: use `t3.micro` (or another **free-tier-eligible** type) if your account only allows Free Tier launches. Use `t3.medium` or larger for better Ollama performance once your account can launch non-free-tier instances
- `architecture`: `amd64` for `t3.*`, `arm64` for `t4g.*` Graviton instances

### Important OCI config fields

- `compartment_id`: required
- `availability_domain`: optional, leave blank to let the script try all available ADs
- `ssh_public_key_path`: required
- `user_data_path`: optional cloud-init shell script

## Run The AWS Provisioner

```bash
cd backend/deploy
source .venv/bin/activate
python scripts/provision_aws_backend.py --config config/aws-backend.json
```

Expected result:

- JSON output containing `instance_id`, `public_ip`, and `private_ip`
- a created or reused IAM role
- a created or reused instance profile
- a created or reused security group

## Run The AWS Ollama Provisioner

Run **after** the backend exists so you can copy the backend security group ID into `config/aws-ollama.json`.

```bash
cd backend/deploy
source .venv/bin/activate
python scripts/provision_aws_ollama.py --config config/aws-ollama.json
```

Expected result:

- JSON with `private_ip` and hints `ollama_url_private`
- on the backend `.env`, set `OLLAMA_BASE_URL` to `http://<ollama-private-ip>:11434`

Then SSM into the Ollama instance and run `ollama pull` for your models.

## Run The OCI Provisioner

```bash
cd backend/deploy
source .venv/bin/activate
python scripts/provision_oci_ollama.py --config config/oci-ollama.json
```

Expected result:

- JSON output containing `instance_id`, `public_ip`, and `private_ip`
- a created or reused VCN, subnet, route table, and security list
- a created or reused OCI compute instance

## Post-Provision Manual Steps

After the scripts succeed, continue with the main deployment guide.

### AWS backend machine

1. Connect through Session Manager.
2. Clone the backend repo.
3. Create `.env`.
4. Create the `systemd` unit.
5. Configure Nginx.
6. Set up DuckDNS or your real domain.
7. Run Certbot.

### OCI Ollama machine

1. SSH into the instance.
2. Verify `ollama` is running.
3. Pull:
   - `qwen2.5:3b`
   - `nomic-embed-text`
4. Install Tailscale.
5. Join the same tailnet as the AWS backend.

### Cross-cloud connection

From AWS EC2:

```bash
curl http://<OCI_TAILSCALE_IP>:11434/api/tags
```

Once that works, update the backend `.env`:

```env
OLLAMA_BASE_URL=http://<OCI_TAILSCALE_IP>:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

## Safety Notes

- The AWS script intentionally does not create an Elastic IP.
- The AWS script intentionally does not open SSH publicly.
- The OCI script intentionally does not expose port `11434` publicly.
- The OCI script only opens SSH publicly by default.
- Both scripts are idempotent at a basic level: they try to reuse resources with the same configured names instead of blindly creating duplicates.

## Limits Of Automation

These scripts are infrastructure helpers, not a full one-click platform installer.

They do not solve:

- account signup and verification
- free-tier quota availability issues
- expired AWS credits or post-free-tier billing
- OCI capacity shortages for Always Free shapes
- TLS certificate issuance for a domain you do not control
- interactive Tailscale approval

## OCI Capacity Notes

OCI Always Free ARM capacity is often the hardest part of this whole setup.

If the OCI script fails with `Out of host capacity`:

1. leave `availability_domain` blank so the script can try every AD
2. retry later
3. reduce `ocpus` and `memory_gb` in `config/oci-ollama.json`
4. if your account supports it, try another OCI region

For example, if `4 OCPU / 24 GB` fails repeatedly, try `2 OCPU / 12 GB` first.

## Suggested Workflow

1. Run the AWS script.
2. Run the OCI script.
3. Follow `backend/docs/AWS_ZERO_COST_DEPLOYMENT.md`.
4. Keep OAuth disabled initially.
5. Enable the scheduler only after `/api/health` is healthy.
