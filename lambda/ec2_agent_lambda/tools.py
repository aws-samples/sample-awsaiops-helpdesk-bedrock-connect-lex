import json
import logging
import boto3
from typing import List

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ec2_client = boto3.client("ec2")


def get_ec2_details_tool(query: str) -> str:
    try:
        payload = json.loads(query)
        tag_key = payload.get("tag_key")
        tag_value = payload.get("tag_value")

        if not tag_key or not tag_value:
            return json.dumps({"message": "Missing tag_key or tag_value in query."})

        filters = [{"Name": f"tag:{tag_key}", "Values": [tag_value]}]
        instances = ec2_client.describe_instances(Filters=filters)

        details = [
            {
                "InstanceId": i["InstanceId"],
                "State": i["State"]["Name"],
                "InstanceType": i["InstanceType"],
                "Tags": i.get("Tags", []),
            }
            for r in instances.get("Reservations", [])
            for i in r.get("Instances", [])
        ]

        return json.dumps({"instances": details})
    except Exception as e:
        logger.error(f"Failed to fetch EC2 instance details: {e}")
        return json.dumps({"message": f"Error: {str(e)}"})


def get_ec2_networking_tool(query: str) -> str:
    try:
        payload = json.loads(query)
        instance_ids: List[str] = payload.get("instance_ids")

        if not instance_ids or not isinstance(instance_ids, list):
            return json.dumps({"message": "Missing or invalid instance_ids in query."})

        response = ec2_client.describe_network_interfaces(
            Filters=[{"Name": "attachment.instance-id", "Values": instance_ids}]
        )

        networking = [
            {
                "NetworkInterfaceId": ni["NetworkInterfaceId"],
                "PrivateIpAddress": ni.get("PrivateIpAddress"),
                "SubnetId": ni.get("SubnetId"),
                "VpcId": ni.get("VpcId"),
                "InstanceId": ni.get("Attachment", {}).get("InstanceId"),
            }
            for ni in response.get("NetworkInterfaces", [])
        ]

        return json.dumps({"networking": networking})
    except Exception as e:
        logger.error(f"Failed to fetch EC2 networking info: {e}")
        return json.dumps({"message": f"Error: {str(e)}"})


def get_ec2_storage_tool(query: str) -> str:
    try:
        payload = json.loads(query)
        instance_ids: List[str] = payload.get("instance_ids")

        if not instance_ids or not isinstance(instance_ids, list):
            return json.dumps({"message": "Missing or invalid instance_ids in query."})

        response = ec2_client.describe_instances(InstanceIds=instance_ids)

        storage = []
        for r in response.get("Reservations", []):
            for i in r.get("Instances", []):
                volumes = [
                    {
                        "InstanceId": i["InstanceId"],
                        "VolumeId": mapping["Ebs"]["VolumeId"],
                        "DeviceName": mapping["DeviceName"],
                    }
                    for mapping in i.get("BlockDeviceMappings", [])
                    if "Ebs" in mapping
                ]
                storage.extend(volumes)

        return json.dumps({"storage": storage})
    except Exception as e:
        logger.error(f"Failed to fetch EC2 storage info: {e}")
        return json.dumps({"message": f"Error: {str(e)}"})


def start_ec2_instances_tool(query: str) -> str:
    """Start EC2 instances by instance IDs"""
    try:
        payload = json.loads(query)
        instance_ids: List[str] = payload.get("instance_ids")

        if not instance_ids or not isinstance(instance_ids, list):
            return json.dumps({"message": "Missing or invalid instance_ids in query."})

        response = ec2_client.start_instances(InstanceIds=instance_ids)
        
        starting_instances = [
            {
                "InstanceId": instance["InstanceId"],
                "CurrentState": instance["CurrentState"]["Name"],
                "PreviousState": instance["PreviousState"]["Name"]
            }
            for instance in response.get("StartingInstances", [])
        ]

        return json.dumps({
            "message": f"Successfully initiated start for {len(starting_instances)} instances",
            "instances": starting_instances
        })
    except Exception as e:
        logger.error(f"Failed to start EC2 instances: {e}")
        return json.dumps({"message": f"Error: {str(e)}"})


def stop_ec2_instances_tool(query: str) -> str:
    """Stop EC2 instances by instance IDs"""
    try:
        payload = json.loads(query)
        instance_ids: List[str] = payload.get("instance_ids")
        force = payload.get("force", False)

        if not instance_ids or not isinstance(instance_ids, list):
            return json.dumps({"message": "Missing or invalid instance_ids in query."})

        response = ec2_client.stop_instances(InstanceIds=instance_ids, Force=force)
        
        stopping_instances = [
            {
                "InstanceId": instance["InstanceId"],
                "CurrentState": instance["CurrentState"]["Name"],
                "PreviousState": instance["PreviousState"]["Name"]
            }
            for instance in response.get("StoppingInstances", [])
        ]

        return json.dumps({
            "message": f"Successfully initiated stop for {len(stopping_instances)} instances",
            "instances": stopping_instances
        })
    except Exception as e:
        logger.error(f"Failed to stop EC2 instances: {e}")
        return json.dumps({"message": f"Error: {str(e)}"})


def list_all_ec2_instances_tool(query: str) -> str:
    """List all EC2 instances with basic information"""
    try:
        payload = json.loads(query) if query else {}
        state_filter = payload.get("state")  # Optional state filter like 'running', 'stopped', etc.
        
        filters = []
        if state_filter:
            filters.append({"Name": "instance-state-name", "Values": [state_filter]})
        
        response = ec2_client.describe_instances(Filters=filters)
        
        instances = []
        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                instance_info = {
                    "InstanceId": instance["InstanceId"],
                    "InstanceType": instance["InstanceType"],
                    "State": instance["State"]["Name"],
                    "LaunchTime": instance["LaunchTime"].isoformat() if "LaunchTime" in instance else None,
                    "PrivateIpAddress": instance.get("PrivateIpAddress"),
                    "PublicIpAddress": instance.get("PublicIpAddress"),
                    "Tags": {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}
                }
                instances.append(instance_info)
        
        return json.dumps({
            "message": f"Found {len(instances)} instances",
            "instances": instances
        })
    except Exception as e:
        logger.error(f"Failed to list EC2 instances: {e}")
        return json.dumps({"message": f"Error: {str(e)}"})
