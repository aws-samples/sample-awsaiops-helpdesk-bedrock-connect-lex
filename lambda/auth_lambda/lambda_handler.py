import json
import boto3
import os
from botocore.exceptions import ClientError

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb')
table_name = os.environ['EMPLOYEE_TABLE_NAME']
table = dynamodb.Table(table_name)

def lambda_handler(event, context):
    """
    Employee Authentication Lambda
    Validates employee ID against DynamoDB table
    """
    
    print(f"Authentication request: {json.dumps(event)}")
    
    try:
        # Extract employee ID from event
        emp_id = None
        
        # Handle different event sources (Lex, API Gateway, etc.)
        if 'currentIntent' in event:
            # Lex V1 format
            slots = event['currentIntent']['slots']
            emp_id = slots.get('empId')
        elif 'sessionState' in event:
            # Lex V2 format
            slots = event['sessionState']['intent']['slots']
            emp_id = slots.get('empId', {}).get('value', {}).get('interpretedValue')
        elif 'empId' in event:
            # Direct invocation
            emp_id = event['empId']
        elif 'body' in event:
            # API Gateway
            body = json.loads(event['body'])
            emp_id = body.get('empId')
        
        if not emp_id:
            return create_response(False, "Employee ID not provided")
        
        # Query DynamoDB
        print(f"Authenticating employee ID: {emp_id}")
        
        response = table.get_item(
            Key={'empId': str(emp_id)}
        )
        
        if 'Item' in response:
            employee = response['Item']
            print(f"Employee found: {employee.get('name', 'Unknown')}")
            
            return create_response(True, "Authentication successful", {
                'empId': employee['empId'],
                'name': employee.get('name', 'Unknown'),
                'department': employee.get('department', 'Unknown'),
                'role': employee.get('role', 'Employee')
            })
        else:
            print(f"Employee ID {emp_id} not found")
            return create_response(False, "Invalid employee ID")
            
    except ClientError as e:
        error_msg = f"DynamoDB error: {e.response['Error']['Message']}"
        print(error_msg)
        return create_response(False, error_msg)
        
    except Exception as e:
        error_msg = f"Authentication error: {str(e)}"
        print(error_msg)
        return create_response(False, error_msg)

def create_response(success, message, employee_data=None):
    """Create standardized response"""
    
    response = {
        'statusCode': 200 if success else 400,
        'body': json.dumps({
            'success': success,
            'message': message,
            'employee': employee_data if employee_data else None
        }),
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        }
    }
    
    # For Lex integration
    if success and employee_data:
        response['sessionAttributes'] = {
            'empId': employee_data['empId'],
            'empName': employee_data['name'],
            'empDepartment': employee_data['department'],
            'empRole': employee_data['role'],
            'authenticated': 'true'
        }
    
    return response
