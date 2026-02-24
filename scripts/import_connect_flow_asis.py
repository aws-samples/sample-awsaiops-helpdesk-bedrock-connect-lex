#!/usr/bin/env python3
"""
Import Connect Flow AS-IS with Placeholder Replacement
- Uses the existing Connect-VoiceID-Sample-Contact-Flow-v3.json as-is
- Replaces placeholders with actual values from CDK and Lex
- Imports directly to Connect instance
"""
import boto3
import json
import os
import re

def get_deployment_values():
    """Get all required values from CDK outputs and Lex deployment"""
    
    # Get CDK outputs
    cf = boto3.client('cloudformation')
    response = cf.describe_stacks(StackName='AwsAIOpsCenterStack')
    outputs = response['Stacks'][0]['Outputs']
    
    values = {}
    account_id = boto3.client('sts').get_caller_identity()['Account']
    region = boto3.Session().region_name or 'us-east-1'
    
    for output in outputs:
        if output['OutputKey'] == 'AuthenticationLambdaArn':
            values['auth_lambda_arn'] = output['OutputValue']
        elif output['OutputKey'] == 'EmployeeTableName':
            values['employee_table'] = output['OutputValue']
            # Create DynamoDB ARN
            values['dynamodb_arn'] = f"arn:aws:dynamodb:{region}:{account_id}:table/{output['OutputValue']}"
    
    # Get Connect instance
    resources = cf.describe_stack_resources(StackName='AwsAIOpsCenterStack')
    for resource in resources['StackResources']:
        if resource['ResourceType'] == 'AWS::Connect::Instance':
            values['connect_instance_id'] = resource['PhysicalResourceId'].split('/')[-1]
            values['connect_instance_arn'] = resource['PhysicalResourceId']
    
    # Get Lex bot information and create ARNs
    lex = boto3.client('lexv2-models')
    bots = lex.list_bots()['botSummaries']
    
    for bot in bots:
        if bot['botName'] == 'awsOpsAuth':
            values['auth_bot_id'] = bot['botId']
            # Get bot alias for ARN
            aliases = lex.list_bot_aliases(botId=bot['botId'])['botAliasSummaries']
            test_alias = next((alias for alias in aliases if alias['botAliasName'] == 'TestBotAlias'), None)
            if test_alias:
                values['auth_bot_arn'] = f"arn:aws:lex:{region}:{account_id}:bot-alias/{bot['botId']}/{test_alias['botAliasId']}"
        elif bot['botName'] == 'awsOpsAgentBot':
            values['agent_bot_id'] = bot['botId']
            # Get bot alias for ARN
            aliases = lex.list_bot_aliases(botId=bot['botId'])['botAliasSummaries']
            test_alias = next((alias for alias in aliases if alias['botAliasName'] == 'TestBotAlias'), None)
            if test_alias:
                values['agent_bot_arn'] = f"arn:aws:lex:{region}:{account_id}:bot-alias/{bot['botId']}/{test_alias['botAliasId']}"
    
    return values

def replace_placeholders_in_flow(flow_content, values):
    """Replace all placeholders in the Connect flow JSON"""
    
    print("🔄 Replacing placeholders in Connect flow...")
    
    # Replace Lambda ARN placeholder
    if 'AUTHENTICATION_LAMBDA_ARN' in flow_content:
        flow_content = flow_content.replace('AUTHENTICATION_LAMBDA_ARN', values['auth_lambda_arn'])
        print(f"   ✅ Replaced Lambda ARN: {values['auth_lambda_arn']}")
    
    # Replace Lex bot ARNs in bot configurations
    if 'awsOpsAuth_BOT_ARN' in flow_content and values.get('auth_bot_arn'):
        flow_content = flow_content.replace('awsOpsAuth_BOT_ARN', values['auth_bot_arn'])
        print(f"   ✅ Replaced Auth Bot ARN: {values['auth_bot_arn']}")
    
    if 'awsOpsAgentBot_BOT_ARN' in flow_content and values.get('agent_bot_arn'):
        flow_content = flow_content.replace('awsOpsAgentBot_BOT_ARN', values['agent_bot_arn'])
        print(f"   ✅ Replaced Agent Bot ARN: {values['agent_bot_arn']}")
    
    # Replace Lex bot configurations dynamically
    # Replace awsOpsAuth bot configuration
    if values.get('auth_bot_arn'):
        # Pattern: "V2,us-east-1,BOTID,awsOpsAuth" -> ARN
        auth_bot_pattern = f'"V2,us-east-1,{values.get("auth_bot_id", "")},awsOpsAuth"'
        if auth_bot_pattern in flow_content:
            flow_content = flow_content.replace(auth_bot_pattern, f'"{values["auth_bot_arn"]}"')
            print(f"   ✅ Replaced Auth Bot Config with ARN")
    
    # Replace awsOpsAgentBot bot configuration  
    if values.get('agent_bot_arn'):
        # Pattern: "V2,us-east-1,BOTID,awsOpsAgentBot" -> ARN
        agent_bot_pattern = f'"V2,us-east-1,{values.get("agent_bot_id", "")},awsOpsAgentBot"'
        if agent_bot_pattern in flow_content:
            flow_content = flow_content.replace(agent_bot_pattern, f'"{values["agent_bot_arn"]}"')
            print(f"   ✅ Replaced Agent Bot Config with ARN")
    
    # Replace generic bot ID patterns if present
    if values.get('auth_bot_id'):
        flow_content = flow_content.replace(f'"{values["auth_bot_id"]}"', f'"{values.get("auth_bot_arn", values["auth_bot_id"])}"')
    
    if values.get('agent_bot_id'):
        flow_content = flow_content.replace(f'"{values["agent_bot_id"]}"', f'"{values.get("agent_bot_arn", values["agent_bot_id"])}"')
    
    # Replace DynamoDB ARN
    if 'DYNAMODB_ARN' in flow_content and values.get('dynamodb_arn'):
        flow_content = flow_content.replace('DYNAMODB_ARN', values['dynamodb_arn'])
        print(f"   ✅ Replaced DynamoDB ARN: {values['dynamodb_arn']}")
    
    # Replace Connect instance ID in ARNs if present
    if 'CONNECT_INSTANCE_ID' in flow_content:
        flow_content = flow_content.replace('CONNECT_INSTANCE_ID', values['connect_instance_id'])
        print(f"   ✅ Replaced Connect Instance ID: {values['connect_instance_id']}")
    
    # Replace account ID if present
    account_id = boto3.client('sts').get_caller_identity()['Account']
    if 'ACCOUNT_ID' in flow_content:
        flow_content = flow_content.replace('ACCOUNT_ID', account_id)
        print(f"   ✅ Replaced Account ID: {account_id}")
    
    # Replace region if present
    region = boto3.Session().region_name or 'us-east-1'
    if 'REGION' in flow_content:
        flow_content = flow_content.replace('REGION', region)
        print(f"   ✅ Replaced Region: {region}")
    
    # Replace bot names/IDs if present (for backward compatibility)
    if 'AUTH_BOT_ID' in flow_content:
        flow_content = flow_content.replace('AUTH_BOT_ID', values.get('auth_bot_id', 'awsOpsAuth'))
        print(f"   ✅ Replaced Auth Bot ID: {values.get('auth_bot_id', 'awsOpsAuth')}")
    
    if 'AGENT_BOT_ID' in flow_content:
        flow_content = flow_content.replace('AGENT_BOT_ID', values.get('agent_bot_id', 'awsOpsAgentBot'))
        print(f"   ✅ Replaced Agent Bot ID: {values.get('agent_bot_id', 'awsOpsAgentBot')}")
    
    # Replace hardcoded ARNs with current bot ARNs
    if values.get('auth_bot_arn'):
        # Replace hardcoded auth bot ARN
        flow_content = flow_content.replace(
            'arn:aws:lex:us-east-1:624288001313:bot-alias/BEGGUERCM0/TSTALIASID',
            values['auth_bot_arn']
        )
        print(f"   ✅ Replaced hardcoded Auth Bot ARN with: {values['auth_bot_arn']}")
    
    if values.get('agent_bot_arn'):
        # Replace hardcoded agent bot ARN
        flow_content = flow_content.replace(
            'arn:aws:lex:us-east-1:624288001313:bot-alias/0XP59CYXT8/TSTALIASID',
            values['agent_bot_arn']
        )
        print(f"   ✅ Replaced hardcoded Agent Bot ARN with: {values['agent_bot_arn']}")
    
    return flow_content

def setup_lambda_permissions(auth_lambda_arn, connect_instance_arn):
    """Setup Lambda permissions for Connect to invoke authentication function"""
    
    lambda_client = boto3.client('lambda')
    
    try:
        print("🔐 Setting up Lambda permissions for Connect...")
        
        # Extract function name from ARN
        function_name = auth_lambda_arn.split(':')[-1]
        
        # Add permission for Connect to invoke Lambda
        lambda_client.add_permission(
            FunctionName=function_name,
            StatementId='connect-invoke-permission',
            Action='lambda:InvokeFunction',
            Principal='connect.amazonaws.com',
            SourceArn=connect_instance_arn
        )
        
        print(f"   ✅ Lambda permission added for Connect")
        
    except lambda_client.exceptions.ResourceConflictException:
        print(f"   ✅ Lambda permission already exists")
    except Exception as e:
        print(f"   ⚠️  Error setting Lambda permission: {e}")

def import_connect_flow_asis(connect_instance_id, flow_content):
    """Import the Connect flow exactly as provided"""
    
    connect = boto3.client('connect')
    
    try:
        print(f"📞 Importing Connect flow AS-IS to instance: {connect_instance_id}")
        
        # Validate JSON first
        try:
            flow_data = json.loads(flow_content)
            print("   ✅ Flow JSON is valid")
        except json.JSONDecodeError as e:
            print(f"   ❌ Invalid JSON: {e}")
            return None, None
        
        # Generate unique flow name with timestamp
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        flow_name = f'AWS-AI-Ops-Center-VoiceID-Flow-{timestamp}'
        
        # Create the contact flow
        response = connect.create_contact_flow(
            InstanceId=connect_instance_id,
            Name=flow_name,
            Type='CONTACT_FLOW',
            Description='AWS AI Operations Center contact flow with VoiceID and Bedrock agent integration - Updated with ARNs',
            Content=flow_content,
            Tags={
                'Project': 'AWS-AI-Ops-Center',
                'Environment': 'Production',
                'CreatedBy': 'Automated-Script',
                'FlowType': 'VoiceID-Sample',
                'Version': timestamp
            }
        )
        
        flow_id = response['ContactFlowId']
        flow_arn = response['ContactFlowArn']
        
        print(f"   ✅ Flow imported successfully!")
        print(f"   📋 Flow Name: {flow_name}")
        print(f"   📋 Flow ID: {flow_id}")
        print(f"   🔗 Flow ARN: {flow_arn}")
        
        return flow_id, flow_arn
        
    except Exception as e:
        print(f"   ❌ Error importing flow: {e}")
        
        # Try to get more details about the error
        if hasattr(e, 'response'):
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', 'No details')
            print(f"   📋 Error Code: {error_code}")
            print(f"   📋 Error Message: {error_message}")
        
        return None, None

def main():
    print("📞 CONNECT FLOW IMPORT AS-IS")
    print("=" * 40)
    
    # Get all deployment values
    print("📋 Getting deployment values...")
    try:
        values = get_deployment_values()
        print(f"   ✅ Connect Instance: {values.get('connect_instance_id', 'Not found')}")
        print(f"   ✅ Auth Lambda ARN: {values.get('auth_lambda_arn', 'Not found')}")
        print(f"   ✅ Auth Bot ARN: {values.get('auth_bot_arn', 'Not found')}")
        print(f"   ✅ Agent Bot ARN: {values.get('agent_bot_arn', 'Not found')}")
        print(f"   ✅ DynamoDB ARN: {values.get('dynamodb_arn', 'Not found')}")
        print(f"   ✅ Employee Table: {values.get('employee_table', 'Not found')}")
    except Exception as e:
        print(f"❌ Error getting deployment values: {e}")
        return
    
    if not values.get('connect_instance_id'):
        print("❌ Could not find Connect instance from CDK")
        return
    
    # Load the Connect flow JSON
    script_dir = os.path.dirname(os.path.abspath(__file__))
    flow_file = os.path.join(script_dir, 'connect-flow-template.json')
    
    try:
        with open(flow_file, 'r', encoding='utf-8') as f:
            original_flow = f.read()
        print(f"✅ Loaded Connect flow: {flow_file}")
        print(f"   📊 Flow size: {len(original_flow)} characters")
    except Exception as e:
        print(f"❌ Error loading flow file: {e}")
        return
    
    # Replace placeholders
    updated_flow = replace_placeholders_in_flow(original_flow, values)
    
    # Setup Lambda permissions
    if values.get('auth_lambda_arn') and values.get('connect_instance_arn'):
        setup_lambda_permissions(values['auth_lambda_arn'], values['connect_instance_arn'])
    
    # Import the flow AS-IS
    flow_id, flow_arn = import_connect_flow_asis(values['connect_instance_id'], updated_flow)
    
    if flow_id:
        print("\n🎉 CONNECT FLOW IMPORT SUCCESSFUL!")
        print("=" * 40)
        print(f"✅ Connect Instance: {values['connect_instance_id']}")
        print(f"✅ Contact Flow ID: {flow_id}")
        print(f"✅ Contact Flow ARN: {flow_arn}")
        print(f"✅ Flow Name: AWS-AI-Ops-Center-VoiceID-Flow")
        
        print("\n🎯 NEXT STEPS:")
        print("1. Go to Amazon Connect Console")
        print("2. Navigate to Routing → Contact flows")
        print("3. Find 'AWS-AI-Ops-Center-VoiceID-Flow'")
        print("4. Assign to a phone number or chat widget")
        print("5. Test with employee IDs: EMP001, EMP002, EMP003, EMP004, EMP005, 12345")
        
        print("\n🎊 AWS AI OPS CENTER IS NOW COMPLETE!")
        
    else:
        print("\n❌ Connect flow import failed")
        print("Check the error messages above for details")

if __name__ == "__main__":
    main()
