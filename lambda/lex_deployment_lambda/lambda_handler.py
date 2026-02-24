import json
import boto3
import time
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

def lambda_handler(event, context):
    """Complete Lex deployment automation with WORKING Bedrock structure"""
    
    print(f"Lambda invoked with event: {json.dumps(event)}")
    
    try:
        # Get agent info from event
        agent_id = event.get('agentId')
        alias_id = event.get('aliasId')
        
        if not agent_id or not alias_id:
            raise Exception(f"Missing agent info: agentId={agent_id}, aliasId={alias_id}")
        
        print(f"Starting complete Lex deployment with Agent: {agent_id}:{alias_id}")
        
        # Get Connect instance ID
        connect_instance_id = get_connect_instance_id()
        if not connect_instance_id:
            raise Exception("Could not find Connect instance")
        
        print(f"Connect instance: {connect_instance_id}")
        
        # Deploy complete Lex infrastructure
        auth_bot_id, agent_bot_id, supervisor_intent_id, bedrock_success = deploy_complete_lex(agent_id, alias_id)
        
        if auth_bot_id and agent_bot_id:
            print(f"✅ Bots created: awsOpsAuth={auth_bot_id}, awsOpsAgentBot={agent_bot_id}")
            
            # Configure resource policies and logging
            configure_policies_and_logging(auth_bot_id, agent_bot_id, connect_instance_id)
            
            result = {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Complete Lex deployment successful with 100% automation',
                    'awsOpsAuth': auth_bot_id,
                    'awsOpsAgentBot': agent_bot_id,
                    'supervisorIntent': supervisor_intent_id,
                    'bedrockConfigured': bedrock_success,
                    'connectInstance': connect_instance_id,
                    'bedrockAgent': f"{agent_id}:{alias_id}"
                })
            }
            
            print(f"✅ Complete deployment successful: {result}")
            return result
        else:
            raise Exception("Failed to create Lex bots")
            
    except Exception as e:
        error_msg = f"Lambda deployment error: {str(e)}"
        print(error_msg)
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': error_msg})
        }

def get_connect_instance_id():
    """Get Connect instance ID from CloudFormation stack"""
    try:
        cf = boto3.client('cloudformation')
        resources = cf.describe_stack_resources(StackName='AwsAIOpsCenterStack')
        for resource in resources['StackResources']:
            if resource['ResourceType'] == 'AWS::Connect::Instance':
                return resource['PhysicalResourceId'].split('/')[-1]
        return None
    except Exception as e:
        print(f"Error getting Connect instance: {e}")
        return None

def deploy_complete_lex(agent_id, alias_id):
    """Complete Lex deployment with WORKING Bedrock structure"""
    lex = boto3.client('lexv2-models')
    logs = boto3.client('logs')
    account_id = boto3.client('sts').get_caller_identity()['Account']
    role_arn = f"arn:aws:iam::{account_id}:role/aws-service-role/lexv2.amazonaws.com/AWSServiceRoleForLexV2Bots"
    
    try:
        # Delete existing bots
        print("Cleaning up existing bots...")
        existing_bots = lex.list_bots()['botSummaries']
        for bot in existing_bots:
            if 'awsOps' in bot['botName']:
                print(f"Deleting existing bot: {bot['botName']}")
                try:
                    lex.delete_bot(botId=bot['botId'], skipResourceInUseCheck=True)
                except Exception as e:
                    print(f"Error deleting bot {bot['botName']}: {e}")
        
        time.sleep(30)  # Wait for AWS resource deletion to complete  # nosemgrep: arbitrary-sleep
        
        # Create log groups
        for log_group in ['/aws/lex/awsOpsAuth', '/aws/lex/awsOpsAgentBot']:
            try:
                logs.create_log_group(logGroupName=log_group)
                print(f"✅ Created log group: {log_group}")
            except logs.exceptions.ResourceAlreadyExistsException:
                print(f"✅ Log group exists: {log_group}")
        
        # Create awsOpsAuth
        print("Creating awsOpsAuth...")
        auth_bot = lex.create_bot(
            botName='awsOpsAuth',
            roleArn=role_arn,
            dataPrivacy={'childDirected': False},
            idleSessionTTLInSeconds=300
        )
        auth_bot_id = auth_bot['botId']
        
        # Create awsOpsAgentBot
        print("Creating awsOpsAgentBot...")
        agent_bot = lex.create_bot(
            botName='awsOpsAgentBot',
            roleArn=role_arn,
            dataPrivacy={'childDirected': False},
            idleSessionTTLInSeconds=300
        )
        agent_bot_id = agent_bot['botId']
        
        print(f"Bots created: {auth_bot_id}, {agent_bot_id}")
        
        # Wait for bots to be available
        time.sleep(15)  # Wait for bot creation to complete before locale setup  # nosemgrep: arbitrary-sleep
        
        # Create locales
        print("Creating locales...")
        lex.create_bot_locale(
            botId=auth_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            nluIntentConfidenceThreshold=0.4
        )
        
        lex.create_bot_locale(
            botId=agent_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            nluIntentConfidenceThreshold=0.4
        )
        
        time.sleep(20)  # Wait for locale creation to complete before intent setup  # nosemgrep: arbitrary-sleep
        
        # Create callerInput intent for awsOpsAuth
        print("Creating callerInput intent...")
        caller_intent = lex.create_intent(
            botId=auth_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            intentName='callerInput',
            description='Caller input intent',
            sampleUtterances=[
                {'utterance': 'my employee id is {empId}'},
                {'utterance': '{empId}'},
                {'utterance': 'employee id {empId}'}
            ]
        )
        
        # Create empId slot
        print("Creating empId slot...")
        lex.create_slot(
            botId=auth_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            intentId=caller_intent['intentId'],
            slotName='empId',
            description='Employee ID slot',
            slotTypeId='AMAZON.AlphaNumeric',
            valueElicitationSetting={
                'slotConstraint': 'Required',
                'promptSpecification': {
                    'messageGroups': [{
                        'message': {
                            'plainTextMessage': {'value': 'Please provide your employee ID'}
                        }
                    }],
                    'maxRetries': 3
                }
            }
        )
        
        # Create basic SupervisorAgentIntent first
        print("Creating basic SupervisorAgentIntent...")
        supervisor_intent = lex.create_intent(
            botId=agent_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            intentName='SupervisorAgentIntent',
            description='SupervisorAgentIntent',
            sampleUtterances=[
                {"utterance": "please give me patching status"},
                {"utterance": "please tell me patching status on my dev instance"},
                {"utterance": "please help me patching status on prod instance"},
                {"utterance": "patching status on test instance"},
                {"utterance": "patch all instances"},
                {"utterance": "patch test instance"},
                {"utterance": "install cloudwatch agent on this instance"}
            ]
        )
        
        supervisor_intent_id = supervisor_intent['intentId']
        print(f"Basic SupervisorAgentIntent created: {supervisor_intent_id}")
        
        # Configure Bedrock with WORKING structure
        print("Configuring Bedrock with WORKING structure...")
        bedrock_success = configure_bedrock_working_structure(agent_bot_id, supervisor_intent_id, agent_id, alias_id)
        
        # Build bots
        print("Building bots...")
        lex.build_bot_locale(botId=auth_bot_id, botVersion='DRAFT', localeId='en_US')
        lex.build_bot_locale(botId=agent_bot_id, botVersion='DRAFT', localeId='en_US')
        
        time.sleep(60)  # Wait for bot build process to complete  # nosemgrep: arbitrary-sleep
        
        print("✅ Complete Lex deployment finished")
        return auth_bot_id, agent_bot_id, supervisor_intent_id, bedrock_success
        
    except Exception as e:
        print(f"❌ Error in complete deployment: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return None, None, None, False

def configure_bedrock_working_structure(bot_id, intent_id, agent_id, alias_id):
    """Configure Bedrock using the WORKING bedrockAgentIntentConfiguration structure"""
    
    try:
        session = boto3.Session()
        credentials = session.get_credentials()
        region = session.region_name or 'us-east-1'
        
        url = f"https://models-v2-lex.{region}.amazonaws.com/bots/{bot_id}/botversions/DRAFT/botlocales/en_US/intents/{intent_id}"
        
        # THE WORKING PAYLOAD STRUCTURE FROM BREAKTHROUGH!
        payload = {
            "intentName": "SupervisorAgentIntent",
            "description": "Bedrock Agent Integration Intent",
            "parentIntentSignature": "AMAZON.BedrockAgentIntent",
            "sampleUtterances": [
                {"utterance": "please give me patching status"},
                {"utterance": "please tell me patching status on my dev instance"},
                {"utterance": "please help me patching status on prod instance"},
                {"utterance": "patching status on test instance"},
                {"utterance": "patch all instances"},
                {"utterance": "patch test instance"},
                {"utterance": "install cloudwatch agent on this instance"}
            ],
            "fulfillmentCodeHook": {"enabled": True},
            "bedrockAgentIntentConfiguration": {          # ← THE WORKING STRUCTURE!
                "bedrockAgentConfiguration": {
                    "agentId": agent_id,
                    "agentAliasId": alias_id
                }
            }
        }
        
        request = AWSRequest(method='PUT', url=url, data=json.dumps(payload))
        request.headers['Content-Type'] = 'application/x-amz-json-1.1'
        SigV4Auth(credentials, 'lex', region).add_auth(request)
        
        response = requests.put(url, data=request.body, headers=dict(request.headers), timeout=120)
        
        if response.status_code == 200:
            print("✅ SUCCESS! Bedrock configured with WORKING structure!")
            return True
        else:
            print(f"❌ Working structure failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Working structure error: {e}")
        return False

def configure_policies_and_logging(auth_bot_id, agent_bot_id, connect_instance_id):
    """Configure resource policies and conversation logging"""
    lex = boto3.client('lexv2-models')
    account_id = boto3.client('sts').get_caller_identity()['Account']
    region = 'us-east-1'
    
    print("Configuring resource policies and logging...")
    
    for bot_id, bot_name in [(auth_bot_id, 'awsOpsAuth'), (agent_bot_id, 'awsOpsAgentBot')]:
        try:
            print(f"Configuring {bot_name}...")
            
            # Get bot aliases
            aliases = lex.list_bot_aliases(botId=bot_id)['botAliasSummaries']
            test_alias = next((alias for alias in aliases if alias['botAliasName'] == 'TestBotAlias'), None)
            
            if not test_alias:
                print(f"⚠️  No TestBotAlias found for {bot_name}")
                continue
            
            bot_alias_id = test_alias['botAliasId']
            bot_version = test_alias['botVersion']
            
            # Update alias with conversation logging
            log_group_arn = f"arn:aws:logs:{region}:{account_id}:log-group:/aws/lex/{bot_name}"
            s3_bucket_arn = f"arn:aws:s3:::connect-data-{account_id}"
            
            lex.update_bot_alias(
                botId=bot_id,
                botAliasId=bot_alias_id,
                botAliasName='TestBotAlias',
                description='test bot alias with Connect integration',
                sentimentAnalysisSettings={'detectSentiment': False},
                conversationLogSettings={
                    'textLogSettings': [{
                        'enabled': True,
                        'destination': {
                            'cloudWatch': {
                                'cloudWatchLogGroupArn': log_group_arn,
                                'logPrefix': bot_name
                            }
                        }
                    }],
                    'audioLogSettings': [{
                        'enabled': True,
                        'destination': {
                            's3Bucket': {
                                's3BucketArn': s3_bucket_arn,
                                'logPrefix': bot_name
                            }
                        }
                    }]
                },
                botVersion=bot_version
            )
            
            # Create resource policy
            bot_alias_arn = f"arn:aws:lex:{region}:{account_id}:bot-alias/{bot_id}/{bot_alias_id}"
            
            resource_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Sid": f"connect-{region}-{connect_instance_id}",
                    "Effect": "Allow",
                    "Principal": {"Service": "connect.amazonaws.com"},
                    "Action": ["lex:RecognizeText", "lex:StartConversation"],
                    "Resource": bot_alias_arn,
                    "Condition": {
                        "StringEquals": {"AWS:SourceAccount": account_id},
                        "ArnEquals": {
                            "AWS:SourceArn": f"arn:aws:connect:{region}:{account_id}:instance/{connect_instance_id}"
                        }
                    }
                }]
            }
            
            lex.create_resource_policy(
                resourceArn=bot_alias_arn,
                policy=json.dumps(resource_policy)
            )
            
            # Tag the alias
            lex.tag_resource(
                resourceARN=bot_alias_arn,
                tags={'AmazonConnectEnabled': 'True'}
            )
            
            print(f"✅ {bot_name} configured with policies and logging")
            
        except Exception as e:
            print(f"⚠️  Error configuring {bot_name}: {e}")
    
    print("✅ Resource policies and logging configuration complete")
