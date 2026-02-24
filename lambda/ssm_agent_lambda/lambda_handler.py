import json
import logging
from typing import Dict, Any
import tools

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function handler to process API requests and route them to the appropriate tool functions.
    """
    logger.info("Received event: %s", event)

    action = event.get("actionGroup")
    api_path = event.get("apiPath")
    parameters = event.get("parameters", [])
    input_text = event.get("inputText")
    http_method = event.get("httpMethod")

    logger.info("Input Text: %s", input_text)

    if not parameters:
        return build_error_response(
            action, api_path, http_method, 400, "Missing parameters"
        )

    try:
        query = parameters[0].get("value")
        logger.info("Query: %s", query)

        response_code, body = process_api_request(api_path, query)
        response_body = {"application/json": {"body": str(body)}}
        logger.info("Response body: %s", response_body)

        action_response = {
            "actionGroup": action,
            "apiPath": api_path,
            "httpMethod": http_method,
            "httpStatusCode": response_code,
            "responseBody": response_body,
        }

        return {"messageVersion": "1.0", "response": action_response}
    except Exception as e:
        logger.exception("Unexpected error in handler")
        return build_error_response(action, api_path, http_method, 500, str(e))


def process_api_request(api_path: str, query: str) -> tuple[int, str]:
    """
    Process the API request based on the api_path.
    """
    try:
        api_handlers = {
            "/get_document_parameters": lambda q: tools.get_document_parameters_tool(q),
            "/execute_ssm_document": lambda q: tools.execute_ssm_document_tool(
                json.loads(q)
            ),
            "/check_command_status": lambda q: tools.check_command_status_tool(q),
            "/list_patch_baselines": lambda q: tools.list_patch_baselines_tool(q),
            "/create_patch_baseline": lambda q: tools.create_patch_baseline_tool(
                json.loads(q)
            ),
            "/describe_patch_baseline": lambda q: tools.describe_patch_baseline_tool(q),
            "/update_patch_baseline": lambda q: tools.update_patch_baseline_tool(
                json.loads(q)
            ),
            "/register_patch_group": lambda q: tools.register_patch_group_tool(
                json.loads(q)
            ),
        }

        if api_path in api_handlers:
            return 200, api_handlers[api_path](query)
        else:
            return 400, f"{api_path} is not a valid API, try another one."
    except Exception as e:
        logger.error(f"Error in process_api_request: {e}")
        return 500, f"Internal server error: {e}"


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
