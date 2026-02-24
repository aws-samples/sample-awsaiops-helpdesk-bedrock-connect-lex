import json
import logging
from typing import Dict, Any
from tools import (
    get_ec2_details_tool,
    get_ec2_networking_tool,
    get_ec2_storage_tool,
    start_ec2_instances_tool,
    stop_ec2_instances_tool,
    list_all_ec2_instances_tool,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info("Received event: %s", json.dumps(event))

    action = event.get("actionGroup")
    api_path = event.get("apiPath")
    parameters = event.get("parameters", [])
    http_method = event.get("httpMethod")

    query = parameters[0].get("value") if parameters else ""
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
    """
    Process the API request based on the api_path.
    """
    try:
        api_handlers = {
            "/get_ec2_details": lambda q: get_ec2_details_tool(q),
            "/get_ec2_networking": lambda q: get_ec2_networking_tool(q),
            "/get_ec2_storage": lambda q: get_ec2_storage_tool(q),
            "/start_ec2_instances": lambda q: start_ec2_instances_tool(q),
            "/stop_ec2_instances": lambda q: stop_ec2_instances_tool(q),
            "/list_all_ec2_instances": lambda q: list_all_ec2_instances_tool(q),
        }

        if api_path in api_handlers:
            return 200, api_handlers[api_path](query)
        else:
            return 400, f"{api_path} is not a valid API, try another one."
    except Exception as e:
        logger.error(f"Error in process_api_request: {e}")
        return 500, f"Internal server error: {e}"
