import json
import logging
from typing import Dict, Any
from tools import (
    create_support_case_tool,
    get_support_cases_tool,
    update_support_case_tool,
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
            "/create_support_case": lambda q: create_support_case_tool(q),
            "/get_support_cases": lambda q: get_support_cases_tool(q),
            "/update_support_case": lambda q: update_support_case_tool(q),
        }

        if api_path in api_handlers:
            return 200, api_handlers[api_path](query)
        else:
            return 400, f"{api_path} is not a valid API, try another one."
    except Exception as e:
        logger.error(f"Error in process_api_request: {e}")
        return 500, f"Internal server error: {e}"
