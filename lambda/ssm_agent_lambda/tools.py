import json
from typing import Dict, List, Union, Any
import boto3
from aws_lambda_powertools import Logger, Tracer

logger = Logger()
tracer = Tracer()
ssm_client = boto3.client("ssm")


@tracer.capture_method
def get_ssm_document_params(document_name: str) -> Dict[str, List[str]]:
    try:
        response = ssm_client.describe_document(Name=document_name)
        params = response["Document"].get("Parameters", [])
        return {
            "required": [p["Name"] for p in params if "DefaultValue" not in p],
            "optional": [p["Name"] for p in params if "DefaultValue" in p],
        }
    except Exception as e:
        logger.error(f"Error retrieving document parameters for {document_name}: {e}")
        return {}


@tracer.capture_method
def execute_ssm(
    document_name: str,
    parameters: Dict[str, List[str]],
    targets: List[Dict[str, Union[str, List[str]]]],
) -> Dict:
    try:
        if not targets:
            logger.error("No targets provided for SSM execution.")
            return {"error": "Missing targets for execution"}

        response = ssm_client.send_command(
            DocumentName=document_name,
            Parameters=parameters,
            Targets=targets,
        )
        logger.info(f"SSM send_command response: {response}")
        return response
    except Exception as e:
        logger.error(f"SSM execution error for {document_name}: {e}")
        return {"error": str(e)}


# Tool functions to be called from the Bedrock Agent Lambda handler


def get_document_parameters_tool(document_name: str) -> str:
    logger.info(f"Tool: get_document_parameters_tool({document_name})")
    params = get_ssm_document_params(document_name)
    if not params:
        return json.dumps(
            {"message": f"No parameters found for document '{document_name}'"}
        )
    return json.dumps({"document_name": document_name, "parameters": params})


def execute_ssm_document_tool(payload: Dict[str, Any]) -> str:
    logger.info(f"Tool: execute_ssm_document_tool with payload: {payload}")

    document_name = payload.get("document_name")
    parameters = payload.get("parameters", {})
    targets = payload.get("targets", [])

    if isinstance(parameters, str):
        parameters = json.loads(parameters)
    if isinstance(targets, str):
        targets = json.loads(targets)

    if not document_name or not parameters or not targets:
        return json.dumps(
            {
                "message": "Missing required fields: document_name, parameters, or targets"
            }
        )

    params_meta = get_ssm_document_params(document_name)
    if not params_meta:
        return json.dumps(
            {"message": f"Unable to fetch parameters for document '{document_name}'"}
        )

    missing = [p for p in params_meta["required"] if p not in parameters]
    if missing:
        return json.dumps(
            {
                "message": f"Missing required parameters for document '{document_name}': {missing}"
            }
        )

    valid_params = {
        k: v
        for k, v in parameters.items()
        if k in (params_meta["required"] + params_meta["optional"])
    }

    response = execute_ssm(document_name, targets=targets, parameters=valid_params)

    if "error" in response:
        return json.dumps(
            {
                "message": f"Failed to execute document '{document_name}': {response['error']}"
            }
        )

    command_id = response.get("Command", {}).get("CommandId", "unknown")
    return json.dumps(
        {
            "message": f"Successfully triggered SSM document '{document_name}'. Command ID: {command_id}."
        }
    )


def check_command_status_tool(command_id: str) -> str:
    logger.info(f"Tool: check_command_status_tool({command_id})")
    try:
        result = ssm_client.list_command_invocations(CommandId=command_id, Details=True)
        if not result.get("CommandInvocations"):
            return json.dumps(
                {"message": f"No status found for Command ID: {command_id}"}
            )

        invocation = result["CommandInvocations"][0]
        status = invocation.get("Status")
        instance_id = invocation.get("InstanceId", "N/A")
        return json.dumps(
            {
                "message": f"Command ID {command_id} on instance {instance_id} has status: {status}."
            }
        )
    except Exception as e:
        logger.error(f"Error checking status for command {command_id}: {e}")
        return json.dumps({"message": f"Failed to retrieve command status: {str(e)}"})


def list_patch_baselines_tool(_: str) -> str:
    logger.info("Tool: list_patch_baselines_tool")
    try:
        baselines = ssm_client.describe_patch_baselines()["BaselineIdentities"]
        results = [
            {
                "BaselineId": b["BaselineId"],
                "BaselineName": b.get("BaselineName"),
                "OperatingSystem": b.get("OperatingSystem"),
                "Description": b.get("Description"),
            }
            for b in baselines
        ]
        return json.dumps({"patch_baselines": results})
    except Exception as e:
        logger.error(f"Error listing patch baselines: {e}")
        return json.dumps({"message": f"Error listing patch baselines: {str(e)}"})


def create_patch_baseline_tool(payload: Dict[str, Any]) -> str:
    logger.info(f"Tool: create_patch_baseline_tool with payload: {payload}")
    try:
        response = ssm_client.create_patch_baseline(
            Name=payload["name"],
            OperatingSystem=payload.get("operating_system", "AMAZON_LINUX_2"),
            ApprovalRules=payload.get("approval_rules"),
            Description=payload.get("description", ""),
            ApprovedPatchesComplianceLevel=payload.get("compliance_level", "CRITICAL"),
        )
        return json.dumps(
            {"message": f"Created patch baseline: {response['BaselineId']}"}
        )
    except Exception as e:
        logger.error(f"Error creating patch baseline: {e}")
        return json.dumps({"message": f"Error creating patch baseline: {str(e)}"})


def describe_patch_baseline_tool(baseline_id: str) -> str:
    logger.info(f"Tool: describe_patch_baseline_tool({baseline_id})")
    try:
        response = ssm_client.get_patch_baseline(BaselineId=baseline_id)
        return json.dumps({"patch_baseline": response})
    except Exception as e:
        logger.error(f"Error describing patch baseline: {e}")
        return json.dumps({"message": f"Error describing patch baseline: {str(e)}"})


def update_patch_baseline_tool(payload: Dict[str, Any]) -> str:
    logger.info(f"Tool: update_patch_baseline_tool with payload: {payload}")
    try:
        response = ssm_client.update_patch_baseline(
            BaselineId=payload["baseline_id"],
            Name=payload.get("name"),
            Description=payload.get("description"),
            ApprovalRules=payload.get("approval_rules"),
        )
        return json.dumps(
            {"message": f"Updated patch baseline: {response['BaselineId']}"}
        )
    except Exception as e:
        logger.error(f"Error updating patch baseline: {e}")
        return json.dumps({"message": f"Error updating patch baseline: {str(e)}"})


def register_patch_group_tool(payload: Dict[str, Any]) -> str:
    logger.info(f"Tool: register_patch_group_tool with payload: {payload}")
    try:
        ssm_client.register_patch_baseline_for_patch_group(
            BaselineId=payload["baseline_id"], PatchGroup=payload["patch_group"]
        )
        return json.dumps(
            {
                "message": f"Patch group '{payload['patch_group']}' registered with baseline '{payload['baseline_id']}'"
            }
        )
    except Exception as e:
        logger.error(f"Error registering patch group: {e}")
        return json.dumps({"message": f"Error registering patch group: {str(e)}"})
