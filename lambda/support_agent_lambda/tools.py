import json
import logging
import boto3
from typing import Dict, Any, List
from datetime import datetime
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize AWS Support client
support_client = boto3.client("support")
cloudwatch_client = boto3.client("logs")


def create_support_case_tool(query: str) -> str:
    """
    Create an AWS Support case based on the provided information.
    """
    try:
        payload = json.loads(query)
        subject = payload.get("subject")
        service_code = payload.get("service_code", "amazon-bedrock")
        category_code = payload.get("category_code", "other")
        severity_code = payload.get("severity_code", "low")
        communication_body = payload.get("communication_body")
        agent_name = payload.get("agent_name")
        error_details = payload.get("error_details", {})
        
        if not subject or not communication_body:
            return json.dumps({
                "message": "Missing required parameters: subject and communication_body are required."
            })
            
        # Enhance the communication body with error details if available
        enhanced_body = communication_body
        if error_details:
            enhanced_body += "\n\n--- Error Details ---\n"
            enhanced_body += f"Agent: {agent_name}\n"
            enhanced_body += f"Error Type: {error_details.get('error_type', 'Unknown')}\n"
            enhanced_body += f"Error Message: {error_details.get('error_message', 'No message provided')}\n"
            enhanced_body += f"Timestamp: {error_details.get('timestamp', datetime.now().isoformat())}\n"
            
            # Add any additional context from the error
            if 'context' in error_details:
                enhanced_body += f"\nContext: {json.dumps(error_details['context'], indent=2)}\n"
        
        try:
            # Create the support case with the correct parameters
            response = support_client.create_case(
                subject=subject,
                serviceCode=service_code,
                categoryCode=category_code,
                severityCode=severity_code,
                communicationBody=enhanced_body,
                ccEmailAddresses=payload.get("cc_email_addresses", []),
                language=payload.get("language", "en"),
                issueType="technical"  # Using technical as the issueType for technical issues
            )
            
            return json.dumps({
                "case_id": response.get("caseId"),
                "message": "Support case created successfully"
            })
            
        except ClientError as err:
            if err.response["Error"]["Code"] == "SubscriptionRequiredException":
                logger.info(
                    "You must have a Business, Enterprise On-Ramp, or Enterprise Support "
                    "plan to use the AWS Support API. \n\tPlease upgrade your subscription to run these "
                    "examples."
                )
                return json.dumps({
                    "message": "Error: You must have a Business, Enterprise On-Ramp, or Enterprise Support plan to use the AWS Support API."
                })
            elif err.response["Error"]["Code"] == "InvalidParameterValueException":
                # Try with different service and category codes
                logger.info("Invalid parameter combination. Trying with general AWS service code.")
                try:
                    response = support_client.create_case(
                        subject=subject,
                        serviceCode="general-info",  # Use general-info as a fallback
                        categoryCode="general-guidance",  # Use general-guidance as a fallback
                        severityCode=severity_code,
                        communicationBody=enhanced_body,
                        ccEmailAddresses=payload.get("cc_email_addresses", []),
                        language=payload.get("language", "en"),
                        issueType="technical"  # Using technical for technical issues
                    )
                    
                    return json.dumps({
                        "case_id": response.get("caseId"),
                        "message": "Support case created successfully with fallback service/category"
                    })
                except Exception as inner_e:
                    logger.error(f"Failed to create support case with fallback parameters: {inner_e}")
                    return json.dumps({"message": f"Error with fallback parameters: {str(inner_e)}"})
            else:
                logger.error(
                    "Couldn't create case. Here's why: %s: %s",
                    err.response["Error"]["Code"],
                    err.response["Error"]["Message"],
                )
                return json.dumps({"message": f"Error: {err.response['Error']['Message']}"})
        
    except Exception as e:
        logger.error(f"Failed to create support case: {e}")
        return json.dumps({"message": f"Error: {str(e)}"})


def get_support_cases_tool(query: str) -> str:
    """
    Get AWS Support cases based on filters.
    """
    try:
        payload = json.loads(query)
        include_resolved = payload.get("include_resolved", False)
        after_time = payload.get("after_time")
        before_time = payload.get("before_time")
        case_id_list = payload.get("case_id_list", [])
        
        # Set up filters
        filters = {
            "includeResolvedCases": include_resolved
        }
        
        if after_time:
            filters["afterTime"] = after_time
            
        if before_time:
            filters["beforeTime"] = before_time
            
        if case_id_list:
            filters["caseIdList"] = case_id_list
        
        try:
            # Get cases
            response = support_client.describe_cases(**filters)
            
            cases = [{
                "case_id": case.get("caseId"),
                "subject": case.get("subject"),
                "status": case.get("status"),
                "service_code": case.get("serviceCode"),
                "category_code": case.get("categoryCode"),
                "severity_code": case.get("severityCode"),
                "submitted_time": case.get("timeCreated"),
                "recent_communications": case.get("recentCommunications", {}).get("communications", [])[:1]
            } for case in response.get("cases", [])]
            
            return json.dumps({"cases": cases})
            
        except ClientError as err:
            if err.response["Error"]["Code"] == "SubscriptionRequiredException":
                logger.info(
                    "You must have a Business, Enterprise On-Ramp, or Enterprise Support "
                    "plan to use the AWS Support API."
                )
                return json.dumps({
                    "message": "Error: You must have a Business, Enterprise On-Ramp, or Enterprise Support plan to use the AWS Support API."
                })
            else:
                logger.error(
                    "Couldn't get cases. Here's why: %s: %s",
                    err.response["Error"]["Code"],
                    err.response["Error"]["Message"],
                )
                return json.dumps({"message": f"Error: {err.response['Error']['Message']}"})
        
    except Exception as e:
        logger.error(f"Failed to get support cases: {e}")
        return json.dumps({"message": f"Error: {str(e)}"})


def update_support_case_tool(query: str) -> str:
    """
    Update an existing AWS Support case.
    """
    try:
        payload = json.loads(query)
        case_id = payload.get("case_id")
        communication_body = payload.get("communication_body")
        
        if not case_id or not communication_body:
            return json.dumps({
                "message": "Missing required parameters: case_id and communication_body are required."
            })
        
        try:
            # Add communication to the case
            response = support_client.add_communication_to_case(
                caseId=case_id,
                communicationBody=communication_body,
                ccEmailAddresses=payload.get("cc_email_addresses", [])
            )
            
            if response.get("result"):
                return json.dumps({
                    "message": "Communication added to case successfully",
                    "case_id": case_id
                })
            else:
                return json.dumps({
                    "message": "Failed to add communication to case",
                    "case_id": case_id
                })
                
        except ClientError as err:
            if err.response["Error"]["Code"] == "SubscriptionRequiredException":
                logger.info(
                    "You must have a Business, Enterprise On-Ramp, or Enterprise Support "
                    "plan to use the AWS Support API."
                )
                return json.dumps({
                    "message": "Error: You must have a Business, Enterprise On-Ramp, or Enterprise Support plan to use the AWS Support API."
                })
            else:
                logger.error(
                    "Couldn't update case. Here's why: %s: %s",
                    err.response["Error"]["Code"],
                    err.response["Error"]["Message"],
                )
                return json.dumps({"message": f"Error: {err.response['Error']['Message']}"})
            
    except Exception as e:
        logger.error(f"Failed to update support case: {e}")
        return json.dumps({"message": f"Error: {str(e)}"})


def get_agent_errors_from_logs(agent_name: str, time_range_minutes: int = 60) -> List[Dict[str, Any]]:
    """
    Helper function to retrieve errors from CloudWatch logs for a specific agent.
    Not exposed directly as an API but can be used by other functions.
    """
    try:
        # Calculate time range
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = end_time - (time_range_minutes * 60 * 1000)
        
        # Construct log group name based on agent naming convention
        log_group_name = f"/aws/lambda/{agent_name}Lambda"
        
        # Query for error logs
        query = "fields @timestamp, @message | filter level='ERROR' | sort @timestamp desc | limit 20"
        
        # Start query
        start_query_response = cloudwatch_client.start_query(
            logGroupName=log_group_name,
            startTime=start_time,
            endTime=end_time,
            queryString=query
        )
        
        query_id = start_query_response['queryId']
        
        # Wait for query to complete
        response = None
        while response is None or response['status'] == 'Running':
            response = cloudwatch_client.get_query_results(queryId=query_id)
            if response['status'] != 'Complete':
                continue
        
        # Process results
        errors = []
        for result in response.get('results', []):
            error_entry = {}
            for field in result:
                if field['field'] == '@timestamp':
                    error_entry['timestamp'] = field['value']
                elif field['field'] == '@message':
                    error_entry['message'] = field['value']
            
            if error_entry:
                errors.append(error_entry)
                
        return errors
        
    except Exception as e:
        logger.error(f"Failed to get agent errors from logs: {e}")
        return []
