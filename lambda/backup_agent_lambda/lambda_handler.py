import json
import logging
from typing import Dict, Any
import tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info("Received event: %s", json.dumps(event))

    action = event.get("actionGroup")
    api_path = event.get("apiPath")
    parameters = event.get("parameters", [])
    http_method = event.get("httpMethod")

    if not parameters:
        return build_error_response(
            action, api_path, http_method, 400, "Missing parameters"
        )

    query = parameters[0].get("value")
    logger.info("Query: %s", query)

    response_code, body = process_api_request(api_path, query)

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action,
            "apiPath": api_path,
            "httpMethod": http_method,
            "httpStatusCode": response_code,
            "responseBody": {"application/json": {"body": str(body)}},
        },
    }


def process_api_request(api_path: str, query: str) -> tuple[int, str]:
    try:
        api_handlers = {
            "/list_backup_plans": lambda q: tools.list_backup_plans_tool(q),
            "/create_backup_plan": lambda q: tools.create_backup_plan_tool(
                json.loads(q)
            ),
            "/describe_backup_plan": lambda q: tools.describe_backup_plan_tool(q),
            "/delete_backup_plan": lambda q: tools.delete_backup_plan_tool(q),
            "/assign_resource_to_backup_plan": lambda q: tools.assign_resource_to_backup_plan_tool(
                json.loads(q)
            ),
            "/list_backup_jobs": lambda q: tools.list_backup_jobs_tool(q),
        }

        if api_path in api_handlers:
            return 200, api_handlers[api_path](query)
        else:
            return 400, f"{api_path} is not a valid API path."
    except Exception as e:
        logger.exception("Error processing request")
        return 500, f"Internal server error: {str(e)}"


def build_error_response(action, api_path, http_method, status_code, message):
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action,
            "apiPath": api_path,
            "httpMethod": http_method,
            "httpStatusCode": status_code,
            "responseBody": {
                "application/json": {"body": json.dumps({"error": message})}
            },
        },
    }
