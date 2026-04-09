#!/usr/bin/env python3
# pyright: reportMissingImports=false
"""Provision a dedicated EC2 host for Ollama (separate from the API backend)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

SSM_POLICY_ARN = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
OLLAMA_PORT = 11434


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        example = path.with_name(f"{path.stem}.example{path.suffix}")
        message = [f"Config file not found: {path}"]
        if example.exists():
            message.append(f"Create it first, for example: cp {example.name} {path.name}")
        raise FileNotFoundError("\n".join(message))
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_deploy_env() -> None:
    deploy_dir = Path(__file__).resolve().parents[1]
    load_dotenv(deploy_dir / ".env")


def read_optional_text(base_dir: Path, relative_path: str | None) -> str:
    if not relative_path:
        return ""
    target = (base_dir / relative_path).resolve()
    return target.read_text(encoding="utf-8")


def ensure_role(iam, role_name: str) -> None:
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        iam.get_role(RoleName=role_name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
            Description="EC2 role for Ollama host (SSM)",
        )
    iam.attach_role_policy(RoleName=role_name, PolicyArn=SSM_POLICY_ARN)


def ensure_instance_profile(iam, profile_name: str, role_name: str) -> None:
    try:
        iam.get_instance_profile(InstanceProfileName=profile_name)["InstanceProfile"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_instance_profile(InstanceProfileName=profile_name)

    profile = iam.get_instance_profile(InstanceProfileName=profile_name)["InstanceProfile"]
    attached_role_names = {role["RoleName"] for role in profile.get("Roles", [])}
    if role_name not in attached_role_names:
        iam.add_role_to_instance_profile(InstanceProfileName=profile_name, RoleName=role_name)
        time.sleep(10)


def get_vpc_id_for_subnet(ec2, subnet_id: str) -> str:
    response = ec2.describe_subnets(SubnetIds=[subnet_id])
    return response["Subnets"][0]["VpcId"]


def authorize_ollama_ingress(
    ec2,
    group_id: str,
    backend_sg_id: str | None,
    cidr: str | None,
) -> None:
    if backend_sg_id:
        try:
            ec2.authorize_security_group_ingress(
                GroupId=group_id,
                IpPermissions=[
                    {
                        "IpProtocol": "tcp",
                        "FromPort": OLLAMA_PORT,
                        "ToPort": OLLAMA_PORT,
                        "UserIdGroupPairs": [{"GroupId": backend_sg_id}],
                    }
                ],
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "InvalidPermission.Duplicate":
                raise
    if cidr:
        try:
            ec2.authorize_security_group_ingress(
                GroupId=group_id,
                IpPermissions=[
                    {
                        "IpProtocol": "tcp",
                        "FromPort": OLLAMA_PORT,
                        "ToPort": OLLAMA_PORT,
                        "IpRanges": [{"CidrIp": cidr}],
                    }
                ],
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "InvalidPermission.Duplicate":
                raise


def ensure_ollama_security_group(
    ec2,
    vpc_id: str,
    group_name: str,
    tags: dict[str, str],
    backend_sg_id: str | None,
    cidr: str | None,
) -> str:
    existing = ec2.describe_security_groups(
        Filters=[
            {"Name": "group-name", "Values": [group_name]},
            {"Name": "vpc-id", "Values": [vpc_id]},
        ]
    )["SecurityGroups"]
    if existing:
        group_id = existing[0]["GroupId"]
    else:
        response = ec2.create_security_group(
            GroupName=group_name,
            Description="Ollama host: port 11434 from backend SG or VPC CIDR only",
            VpcId=vpc_id,
            TagSpecifications=[
                {
                    "ResourceType": "security-group",
                    "Tags": [{"Key": k, "Value": v} for k, v in tags.items()],
                }
            ],
        )
        group_id = response["GroupId"]

    authorize_ollama_ingress(ec2, group_id, backend_sg_id, cidr)
    return group_id


def find_existing_instance(ec2_resource, instance_name: str):
    instances = list(
        ec2_resource.instances.filter(
            Filters=[
                {"Name": "tag:Name", "Values": [instance_name]},
                {
                    "Name": "instance-state-name",
                    "Values": ["pending", "running", "stopping", "stopped"],
                },
            ]
        )
    )
    return instances[0] if instances else None


def resolve_ubuntu_ami(ssm, architecture: str = "amd64") -> str:
    param = f"/aws/service/canonical/ubuntu/server/24.04/stable/current/{architecture}/hvm/ebs-gp3/ami-id"
    return ssm.get_parameter(Name=param)["Parameter"]["Value"]


def launch_instance(
    ec2_resource,
    config: dict[str, Any],
    instance_profile_name: str,
    security_group_id: str,
    image_id: str,
    user_data: str,
):
    tag_specifications = [
        {
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": config["instance_name"]}]
            + [{"Key": k, "Value": v} for k, v in config.get("tags", {}).items()],
        },
        {
            "ResourceType": "volume",
            "Tags": [{"Key": "Name", "Value": f'{config["instance_name"]}-root'}]
            + [{"Key": k, "Value": v} for k, v in config.get("tags", {}).items()],
        },
    ]

    instances = ec2_resource.create_instances(
        ImageId=image_id,
        InstanceType=config.get("instance_type", "t3.medium"),
        MinCount=1,
        MaxCount=1,
        IamInstanceProfile={"Name": instance_profile_name},
        UserData=user_data,
        TagSpecifications=tag_specifications,
        NetworkInterfaces=[
            {
                "DeviceIndex": 0,
                "SubnetId": config["subnet_id"],
                "Groups": [security_group_id],
                "AssociatePublicIpAddress": config.get("associate_public_ip", True),
            }
        ],
        MetadataOptions={"HttpTokens": "required", "HttpEndpoint": "enabled"},
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": config.get("root_volume_gb", 50),
                    "VolumeType": "gp3",
                    "DeleteOnTermination": True,
                },
            }
        ],
    )
    instance = instances[0]
    instance.wait_until_running()
    instance.reload()
    return instance


def summarize_instance(instance) -> dict[str, Any]:
    return {
        "instance_id": instance.id,
        "state": instance.state["Name"],
        "public_ip": instance.public_ip_address,
        "private_ip": instance.private_ip_address,
        "subnet_id": instance.subnet_id,
        "vpc_id": instance.vpc_id,
        "ollama_url_private": f"http://{instance.private_ip_address}:{OLLAMA_PORT}",
        "ollama_url_public": (
            f"http://{instance.public_ip_address}:{OLLAMA_PORT}" if instance.public_ip_address else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to the AWS Ollama JSON config")
    args = parser.parse_args()

    load_deploy_env()
    config_path = Path(args.config).resolve()
    config = load_json(config_path)

    backend_sg = (config.get("backend_security_group_id") or "").strip() or None
    cidr = (config.get("ollama_ingress_cidr") or "").strip() or None
    if not backend_sg and not cidr:
        raise RuntimeError(
            "Set backend_security_group_id (recommended) and/or ollama_ingress_cidr in the config.\n"
            "Example: backend_security_group_id from the backend instance security group (sg-...).\n"
            "Or set ollama_ingress_cidr to your VPC CIDR (e.g. 10.0.0.0/16) if the backend reaches Ollama by private IP."
        )

    if backend_sg:
        bad = "REPLACE" in backend_sg.upper() or "EXAMPLE" in backend_sg.upper()
        if not backend_sg.startswith("sg-") or len(backend_sg) < 12 or bad:
            raise RuntimeError(
                f"Invalid backend_security_group_id: {backend_sg!r}\n"
                "Use the real security group ID attached to your API EC2 instance (e.g. sg-0abc123...).\n"
                "If you used provision_aws_backend.py, find it with:\n"
                "  aws ec2 describe-security-groups --region <region> "
                '--filters Name=group-name,Values=ai-trading-backend-sg --query SecurityGroups[0].GroupId --output text'
            )

    session = boto3.Session(region_name=config["region"])
    iam = session.client("iam")
    ec2 = session.client("ec2")
    ec2_resource = session.resource("ec2")
    ssm = session.client("ssm")
    sts = session.client("sts")

    caller = sts.get_caller_identity()
    print(f"AWS account: {caller['Account']}")
    print(f"Region: {config['region']}")

    ensure_role(iam, config["iam_role_name"])
    ensure_instance_profile(iam, config["instance_profile_name"], config["iam_role_name"])

    vpc_id = get_vpc_id_for_subnet(ec2, config["subnet_id"])
    security_group_id = ensure_ollama_security_group(
        ec2,
        vpc_id=vpc_id,
        group_name=config["security_group_name"],
        tags=config.get("tags", {}),
        backend_sg_id=backend_sg,
        cidr=cidr,
    )

    existing = find_existing_instance(ec2_resource, config["instance_name"])
    if existing:
        print(json.dumps({"status": "exists", **summarize_instance(existing)}, indent=2))
        return

    arch = (config.get("architecture") or "amd64").strip().lower()
    if arch not in ("amd64", "arm64"):
        raise RuntimeError('architecture must be "amd64" or "arm64"')
    image_id = resolve_ubuntu_ami(ssm, architecture=arch)
    user_data = read_optional_text(config_path.parent, config.get("user_data_path"))

    last_error: Exception | None = None
    instance = None
    for _ in range(3):
        try:
            instance = launch_instance(
                ec2_resource,
                config=config,
                instance_profile_name=config["instance_profile_name"],
                security_group_id=security_group_id,
                image_id=image_id,
                user_data=user_data,
            )
            break
        except ClientError as exc:
            last_error = exc
            time.sleep(10)
    if instance is None:
        raise RuntimeError("Failed to launch Ollama EC2 instance after retries.") from last_error

    print(json.dumps({"status": "created", **summarize_instance(instance)}, indent=2))
    print(
        "\nNext: SSM into the Ollama host, then:\n"
        "  ollama pull qwen2.5:3b\n"
        "  ollama pull nomic-embed-text\n"
        "On the backend, set OLLAMA_BASE_URL to the private URL if both instances are in the same VPC."
    )


if __name__ == "__main__":
    main()
