#!/usr/bin/env python3
# pyright: reportMissingImports=false
"""Provision the OCI Always Free Ollama host for the AI Trading Assistant."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any

import oci
from oci.core import models as core_models
from oci.signer import Signer
from oci.exceptions import ServiceError
from dotenv import load_dotenv


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_deploy_env() -> None:
    deploy_dir = Path(__file__).resolve().parents[1]
    load_dotenv(deploy_dir / ".env")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def read_optional_user_data(base_dir: Path, relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    target = (base_dir / relative_path).resolve()
    raw = target.read_text(encoding="utf-8")
    return base64.b64encode(raw.encode("utf-8")).decode("utf-8")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def build_oci_auth_from_env() -> tuple[dict[str, str], Signer]:
    user = require_env("OCI_USER_OCID")
    fingerprint = require_env("OCI_FINGERPRINT")
    tenancy = require_env("OCI_TENANCY_OCID")
    region = require_env("OCI_REGION")
    private_key_path = os.getenv("OCI_PRIVATE_KEY_PATH", "").strip()
    private_key_content = os.getenv("OCI_PRIVATE_KEY", "").strip()
    pass_phrase = os.getenv("OCI_PRIVATE_KEY_PASSPHRASE", "").strip() or None

    signer_kwargs: dict[str, Any] = {
        "tenancy": tenancy,
        "user": user,
        "fingerprint": fingerprint,
        "private_key_file_location": "",
        "pass_phrase": pass_phrase,
    }
    if private_key_content:
        signer_kwargs["private_key_content"] = private_key_content.replace("\\n", "\n")
    elif private_key_path:
        signer_kwargs["private_key_file_location"] = str(Path(private_key_path).expanduser())
    else:
        raise RuntimeError("Set either OCI_PRIVATE_KEY or OCI_PRIVATE_KEY_PATH in the environment.")

    signer = Signer(**signer_kwargs)
    config = {
        "region": region,
        "tenancy": tenancy,
        "user": user,
        "fingerprint": fingerprint,
    }
    if private_key_content:
        config["key_content"] = private_key_content.replace("\\n", "\n")
    elif private_key_path:
        config["key_file"] = str(Path(private_key_path).expanduser())
    return config, signer


def get_availability_domains(identity_client, tenancy_id: str) -> list[str]:
    domains = identity_client.list_availability_domains(tenancy_id).data
    if not domains:
        raise RuntimeError("No availability domains returned for the tenancy.")
    return [domain.name for domain in domains]


def pick_availability_domains(identity_client, tenancy_id: str, configured_name: str | None) -> list[str]:
    domain_names = get_availability_domains(identity_client, tenancy_id)
    if configured_name:
        if configured_name not in domain_names:
            raise RuntimeError(f"Configured availability domain not found: {configured_name}")
        return [configured_name]
    return domain_names


def find_by_name(items: list[Any], display_name: str):
    for item in items:
        if getattr(item, "display_name", None) == display_name:
            return item
    return None


def ensure_vcn(network_client, compartment_id: str, config: dict[str, Any]):
    vcns = network_client.list_vcns(compartment_id=compartment_id).data
    existing = find_by_name(vcns, config["vcn_name"])
    if existing:
        return existing
    details = core_models.CreateVcnDetails(
        compartment_id=compartment_id,
        display_name=config["vcn_name"],
        cidr_blocks=[config["vcn_cidr_block"]],
        dns_label="aitradevcn",
        freeform_tags=config.get("tags", {}),
    )
    response = network_client.create_vcn(details)
    return oci.wait_until(
        network_client,
        network_client.get_vcn(response.data.id),
        "lifecycle_state",
        "AVAILABLE",
    ).data


def ensure_internet_gateway(network_client, compartment_id: str, vcn_id: str, config: dict[str, Any]):
    gateways = network_client.list_internet_gateways(compartment_id=compartment_id, vcn_id=vcn_id).data
    existing = find_by_name(gateways, config["internet_gateway_name"])
    if existing:
        return existing
    details = core_models.CreateInternetGatewayDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=config["internet_gateway_name"],
        is_enabled=True,
        freeform_tags=config.get("tags", {}),
    )
    response = network_client.create_internet_gateway(details)
    return response.data


def ensure_route_table(network_client, compartment_id: str, vcn_id: str, igw_id: str, config: dict[str, Any]):
    route_tables = network_client.list_route_tables(compartment_id=compartment_id, vcn_id=vcn_id).data
    existing = find_by_name(route_tables, config["route_table_name"])
    if existing:
        return existing
    details = core_models.CreateRouteTableDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=config["route_table_name"],
        route_rules=[
            core_models.RouteRule(
                destination="0.0.0.0/0",
                destination_type="CIDR_BLOCK",
                network_entity_id=igw_id,
            )
        ],
        freeform_tags=config.get("tags", {}),
    )
    response = network_client.create_route_table(details)
    return response.data


def ensure_security_list(network_client, compartment_id: str, vcn_id: str, config: dict[str, Any]):
    security_lists = network_client.list_security_lists(compartment_id=compartment_id, vcn_id=vcn_id).data
    existing = find_by_name(security_lists, config["security_list_name"])
    if existing:
        return existing
    details = core_models.CreateSecurityListDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=config["security_list_name"],
        ingress_security_rules=[
            core_models.IngressSecurityRule(
                protocol="6",
                source="0.0.0.0/0",
                tcp_options=core_models.TcpOptions(destination_port_range=core_models.PortRange(min=22, max=22)),
            )
        ],
        egress_security_rules=[
            core_models.EgressSecurityRule(
                protocol="all",
                destination="0.0.0.0/0",
            )
        ],
        freeform_tags=config.get("tags", {}),
    )
    response = network_client.create_security_list(details)
    return response.data


def ensure_subnet(
    network_client,
    compartment_id: str,
    vcn_id: str,
    route_table_id: str,
    security_list_id: str,
    config: dict[str, Any],
):
    subnets = network_client.list_subnets(compartment_id=compartment_id, vcn_id=vcn_id).data
    existing = find_by_name(subnets, config["subnet_name"])
    if existing:
        return existing
    details = core_models.CreateSubnetDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=config["subnet_name"],
        cidr_block=config["subnet_cidr_block"],
        route_table_id=route_table_id,
        security_list_ids=[security_list_id],
        prohibit_public_ip_on_vnic=False,
        freeform_tags=config.get("tags", {}),
        dns_label="aitradesub",
    )
    response = network_client.create_subnet(details)
    return oci.wait_until(
        network_client,
        network_client.get_subnet(response.data.id),
        "lifecycle_state",
        "AVAILABLE",
    ).data


def resolve_image(compute_client, compartment_id: str, config: dict[str, Any]) -> str:
    images = compute_client.list_images(
        compartment_id=compartment_id,
        operating_system=config["image_operating_system"],
        operating_system_version=config["image_operating_system_version"],
        shape=config["shape"],
        sort_by="TIMECREATED",
        sort_order="DESC",
    ).data
    for image in images:
        if image.lifecycle_state == "AVAILABLE":
            return image.id
    raise RuntimeError("No suitable OCI image found for the requested OS/shape combination.")


def find_existing_instance(compute_client, compartment_id: str, display_name: str):
    instances = compute_client.list_instances(compartment_id=compartment_id).data
    for instance in instances:
        if instance.display_name == display_name and instance.lifecycle_state != "TERMINATED":
            return instance
    return None


def get_vnic(network_client, compute_client, compartment_id: str, instance_id: str):
    attachments = compute_client.list_vnic_attachments(compartment_id=compartment_id, instance_id=instance_id).data
    if not attachments:
        raise RuntimeError("No VNIC attachments found for the OCI instance.")
    return network_client.get_vnic(attachments[0].vnic_id).data


def launch_instance(
    compute_client,
    identity_client,
    network_client,
    oci_config: dict[str, str],
    config: dict[str, Any],
    subnet_id: str,
    image_id: str,
    ssh_public_key: str,
    user_data: str | None,
):
    availability_domains = pick_availability_domains(
        identity_client,
        tenancy_id=oci_config["tenancy"],
        configured_name=config.get("availability_domain") or None,
    )

    metadata = {"ssh_authorized_keys": ssh_public_key}
    if user_data:
        metadata["user_data"] = user_data

    capacity_errors: list[str] = []
    for availability_domain in availability_domains:
        details = core_models.LaunchInstanceDetails(
            compartment_id=config["compartment_id"],
            display_name=config["instance_name"],
            availability_domain=availability_domain,
            shape=config["shape"],
            source_details=core_models.InstanceSourceViaImageDetails(
                source_type="image",
                image_id=image_id,
                boot_volume_size_in_gbs=config.get("boot_volume_gb", 80),
            ),
            create_vnic_details=core_models.CreateVnicDetails(
                subnet_id=subnet_id,
                assign_public_ip=True,
                display_name=f'{config["instance_name"]}-vnic',
            ),
            metadata=metadata,
            shape_config=core_models.LaunchInstanceShapeConfigDetails(
                ocpus=config.get("ocpus", 4),
                memory_in_gbs=config.get("memory_gb", 24),
            ),
            freeform_tags=config.get("tags", {}),
        )
        try:
            response = compute_client.launch_instance(details)
            return oci.wait_until(
                compute_client,
                compute_client.get_instance(response.data.id),
                "lifecycle_state",
                "RUNNING",
            ).data
        except ServiceError as exc:
            message = str(getattr(exc, "message", "") or exc)
            if exc.status == 500 and "Out of host capacity" in message:
                capacity_errors.append(availability_domain)
                continue
            raise

    if capacity_errors:
        region = oci_config.get("region", "unknown-region")
        suggested_ocpus = min(int(config.get("ocpus", 4)), 2)
        suggested_memory = min(int(config.get("memory_gb", 24)), 12)
        raise RuntimeError(
            "OCI has no host capacity for this shape right now.\n"
            f"Region: {region}\n"
            f"Attempted availability domains: {', '.join(capacity_errors)}\n"
            "Try one of these:\n"
            "1. Retry later.\n"
            f"2. Lower the shape in config/oci-ollama.json to {suggested_ocpus} OCPU and {suggested_memory} GB RAM.\n"
            "3. If your tenancy allows it, try another region with better Always Free capacity.\n"
            "4. If capacity stays blocked, create the instance manually in the OCI console when stock appears."
        )

    raise RuntimeError("OCI instance launch failed before any availability domain could be used.")


def summarize_instance(instance, vnic) -> dict[str, Any]:
    return {
        "instance_id": instance.id,
        "state": instance.lifecycle_state,
        "public_ip": vnic.public_ip,
        "private_ip": vnic.private_ip,
        "availability_domain": instance.availability_domain,
        "shape": instance.shape,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to the OCI JSON config")
    args = parser.parse_args()

    load_deploy_env()
    config_path = Path(args.config).resolve()
    config = load_json(config_path)
    oci_config, signer = build_oci_auth_from_env()

    identity_client = oci.identity.IdentityClient(oci_config, signer=signer)
    network_client = oci.core.VirtualNetworkClient(oci_config, signer=signer)
    compute_client = oci.core.ComputeClient(oci_config, signer=signer)

    compartment_id = config["compartment_id"]
    vcn = ensure_vcn(network_client, compartment_id, config)
    igw = ensure_internet_gateway(network_client, compartment_id, vcn.id, config)
    route_table = ensure_route_table(network_client, compartment_id, vcn.id, igw.id, config)
    security_list = ensure_security_list(network_client, compartment_id, vcn.id, config)
    subnet = ensure_subnet(
        network_client,
        compartment_id=compartment_id,
        vcn_id=vcn.id,
        route_table_id=route_table.id,
        security_list_id=security_list.id,
        config=config,
    )

    existing = find_existing_instance(compute_client, compartment_id, config["instance_name"])
    if existing:
        vnic = get_vnic(network_client, compute_client, compartment_id, existing.id)
        print(json.dumps({"status": "exists", **summarize_instance(existing, vnic)}, indent=2))
        return

    image_id = resolve_image(compute_client, compartment_id, config)
    ssh_public_key = read_text(Path(config["ssh_public_key_path"]).expanduser())
    user_data = read_optional_user_data(config_path.parent, config.get("user_data_path"))
    instance = launch_instance(
        compute_client,
        identity_client,
        network_client,
        oci_config=oci_config,
        config=config,
        subnet_id=subnet.id,
        image_id=image_id,
        ssh_public_key=ssh_public_key,
        user_data=user_data,
    )
    vnic = get_vnic(network_client, compute_client, compartment_id, instance.id)
    print(
        json.dumps(
            {
                "status": "created",
                "vcn_id": vcn.id,
                "subnet_id": subnet.id,
                **summarize_instance(instance, vnic),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
