import json
import boto3
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

backup_client = boto3.client("backup")


def list_backup_plans_tool(_: str) -> str:
    try:
        response = backup_client.get_paginator('list_backup_plans').paginate().build_full_result()
        for index,job in enumerate(response["BackupPlansList"]):
            response["BackupPlansList"][index]["CreationDate"]=job["CreationDate"].isoformat()
            response["BackupPlansList"][index]["DeletionDate"]=job["DeletionDate"].isoformat()
            response["BackupPlansList"][index]["LastExecutionDate"]=job["LastExecutionDate"].isoformat()
        return json.dumps(response.get("BackupPlansList", []))
    except Exception as e:
        logger.error(f"Error listing backup plans: {e}")
        return json.dumps({"error": str(e)})


def create_backup_plan_tool(payload: dict) -> str:
    try:
        plan_name = payload["plan_name"]
        rules = payload["rules"]
        plan = {
            "BackupPlanName": plan_name,
            "Rules": [
                {
                    "RuleName": r["rule_name"],
                    "TargetBackupVaultName": r.get("vault_name", "Default"),
                    "ScheduleExpression": r["schedule"],
                    "Lifecycle": r.get("lifecycle", {}),
                }
                for r in rules
            ],
        }
        response = backup_client.create_backup_plan(BackupPlan=plan)
        return json.dumps(response)
    except Exception as e:
        logger.error(f"Error creating backup plan: {e}")
        return json.dumps({"error": str(e)})


def describe_backup_plan_tool(plan_id: str) -> str:
    try:
        response = backup_client.get_backup_plan(BackupPlanId=plan_id)
        return json.dumps(response)
    except Exception as e:
        logger.error(f"Error describing backup plan: {e}")
        return json.dumps({"error": str(e)})


def delete_backup_plan_tool(plan_id: str) -> str:
    try:
        response = backup_client.delete_backup_plan(BackupPlanId=plan_id)
        return json.dumps({"message": "Backup plan deleted successfully."})
    except Exception as e:
        logger.error(f"Error deleting backup plan: {e}")
        return json.dumps({"error": str(e)})


def assign_resource_to_backup_plan_tool(payload: dict) -> str:
    try:
        response = backup_client.create_backup_selection(
            BackupPlanId=payload["plan_id"],
            BackupSelection={
                "SelectionName": f"selection-{payload['plan_id']}",
                "IamRoleArn": payload["iam_role_arn"],
                "Resources": [payload["resource_arn"]],
            },
        )
        return json.dumps(response)
    except Exception as e:
        logger.error(f"Error assigning resource to backup plan: {e}")
        return json.dumps({"error": str(e)})


def list_backup_jobs_tool(_: str) -> str:
    try:
        response = backup_client.get_paginator('list_backup_jobs').paginate().build_full_result()
        for index,job in enumerate(response["BackupJobs"]):
            response["BackupJobs"][index]["CreationDate"]=job["CreationDate"].isoformat()
            response["BackupJobs"][index]["CompletionDate"]=job["CompletionDate"].isoformat()
            response["BackupJobs"][index]["StartBy"]=job["StartBy"].isoformat()
        return json.dumps(response.get("BackupJobs", []))
    except Exception as e:
        logger.error(f"Error listing backup jobs: {e}")
        return json.dumps({"error": str(e)})
