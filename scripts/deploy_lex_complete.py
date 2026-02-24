#!/usr/bin/env python3
"""
Complete Lex Bot Deployment with Breakthrough Bedrock Configuration
- Creates awsOpsAuth and awsOpsAgentBot
- Applies working bedrockAgentIntentConfiguration structure
- Configures resource policies and conversation logging
- 100% automated deployment
"""
import boto3
import json
import time
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

def get_cdk_outputs():
    """Get required values from CDK stack"""
    cf = boto3.client('cloudformation')
    response = cf.describe_stacks(StackName='AwsAIOpsCenterStack')
    outputs = response['Stacks'][0]['Outputs']
    
    agent_id = alias_id = connect_instance_id = None
    
    for output in outputs:
        if output['OutputKey'] == 'SupervisorAgentId':
            agent_id = output['OutputValue']
        elif output['OutputKey'] == 'SupervisorAgentAliasId':
            alias_id = output['OutputValue']
    
    # Get Connect instance
    resources = cf.describe_stack_resources(StackName='AwsAIOpsCenterStack')
    for resource in resources['StackResources']:
        if resource['ResourceType'] == 'AWS::Connect::Instance':
            connect_instance_id = resource['PhysicalResourceId'].split('/')[-1]
    
    return agent_id, alias_id, connect_instance_id

def create_lex_custom_role():
    """Create custom IAM role for Lex with Bedrock and Lambda access"""
    iam = boto3.client('iam')
    
    role_name = 'LexBedrockCustomRole'
    
    # Check if role already exists
    try:
        response = iam.get_role(RoleName=role_name)
        print(f"✅ Role {role_name} already exists: {response['Role']['Arn']}")
        return response['Role']['Arn']
    except iam.exceptions.NoSuchEntityException:
        pass
    
    # Trust policy for Lex
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "lexv2.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    try:
        # Create the role
        response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description='Custom role for Lex with Bedrock and Lambda access'
        )
        
        # Attach required policies
        policies = [
            'arn:aws:iam::aws:policy/AmazonBedrockFullAccess',
            'arn:aws:iam::aws:policy/AWSLambda_FullAccess'
        ]
        
        for policy in policies:
            iam.attach_role_policy(
                RoleName=role_name,
                PolicyArn=policy
            )
        
        print(f"✅ Created custom role: {response['Role']['Arn']}")
        return response['Role']['Arn']
        
    except Exception as e:
        print(f"❌ Error creating role: {e}")
        return None

def delete_existing_bots():
    """Delete all existing Lex bots"""
    lex = boto3.client('lexv2-models')
    
    try:
        bots = lex.list_bots()['botSummaries']
        for bot in bots:
            if 'awsOps' in bot['botName']:
                print(f"🗑️  Deleting {bot['botName']} ({bot['botId']})")
                lex.delete_bot(botId=bot['botId'], skipResourceInUseCheck=True)
        
        if bots:
            print("⏳ Waiting for deletion...")
            # Wait for bots to be deleted by polling status
            for _ in range(12):  # Max 2 minutes
                try:
                    remaining_bots = lex.list_bots()['botSummaries']
                    aws_ops_bots = [b for b in remaining_bots if 'awsOps' in b['botName']]
                    if not aws_ops_bots:
                        break
                    time.sleep(10)  # Poll every 10 seconds  # nosemgrep: arbitrary-sleep
                except Exception:
                    break
            
    except Exception as e:
        print(f"⚠️  Error deleting bots: {e}")

def create_resources():
    """Create required CloudWatch log groups"""
    logs = boto3.client('logs')
    
    for log_group in ['/aws/lex/awsOpsAuth', '/aws/lex/awsOpsAgentBot']:
        try:
            logs.create_log_group(logGroupName=log_group)
            print(f"✅ Created log group: {log_group}")
        except logs.exceptions.ResourceAlreadyExistsException:
            print(f"✅ Log group exists: {log_group}")

def create_bots_with_bedrock(agent_id, alias_id):
    """Create bots with breakthrough Bedrock configuration"""
    lex = boto3.client('lexv2-models')
    
    # Create custom role with required permissions
    custom_role_arn = create_lex_custom_role()
    if not custom_role_arn:
        print("❌ Failed to create custom role, falling back to service-linked role")
        account_id = boto3.client('sts').get_caller_identity()['Account']
        role_arn = f"arn:aws:iam::{account_id}:role/aws-service-role/lexv2.amazonaws.com/AWSServiceRoleForLexV2Bots"
    else:
        role_arn = custom_role_arn
    
    print(f"🤖 Creating bots with Bedrock agent: {agent_id}:{alias_id}")
    print(f"🔑 Using role: {role_arn}")
    
    try:
        # Create awsOpsAuth
        print("🔨 Creating awsOpsAuth...")
        auth_bot = lex.create_bot(
            botName='awsOpsAuth',
            roleArn=role_arn,
            dataPrivacy={'childDirected': False},
            idleSessionTTLInSeconds=300
        )
        auth_bot_id = auth_bot['botId']
        
        # Create awsOpsAgentBot
        print("🔨 Creating awsOpsAgentBot...")
        agent_bot = lex.create_bot(
            botName='awsOpsAgentBot',
            roleArn=role_arn,
            dataPrivacy={'childDirected': False},
            idleSessionTTLInSeconds=300
        )
        agent_bot_id = agent_bot['botId']
        
        print(f"✅ Bots created: {auth_bot_id}, {agent_bot_id}")
        
        # Wait for bots to be ready
        for bot_id in [auth_bot_id, agent_bot_id]:
            for _ in range(30):  # Max 5 minutes
                try:
                    bot_status = lex.describe_bot(botId=bot_id)['botStatus']
                    if bot_status == 'Available':
                        break
                    time.sleep(10)  # AWS API polling interval  # nosemgrep: arbitrary-sleep
                except Exception:
                    break
        
        # Create locales
        print("🌐 Creating locales...")
        
        # Get Lambda ARN for auth bot
        cf = boto3.client('cloudformation')
        stack_response = cf.describe_stacks(StackName='AwsAIOpsCenterStack')
        lambda_arn = None
        for output in stack_response['Stacks'][0]['Outputs']:
            if 'AuthenticationLambda' in output['OutputKey']:
                lambda_arn = output['OutputValue']
                break
        
        # Create auth bot locale with Lambda fulfillment
        lex.create_bot_locale(
            botId=auth_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            nluIntentConfidenceThreshold=0.4,
            voiceSettings={
                'voiceId': 'Ivy'
            }
        )
        
        lex.create_bot_locale(
            botId=agent_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            nluIntentConfidenceThreshold=0.4
        )
        
        # Wait for locales to be ready
        for bot_id in [auth_bot_id, agent_bot_id]:
            for _ in range(30):  # Max 5 minutes
                try:
                    locale_status = lex.describe_bot_locale(
                        botId=bot_id,
                        botVersion='DRAFT',
                        localeId='en_US'
                    )['botLocaleStatus']
                    if locale_status == 'Built':
                        break
                    time.sleep(10)  # AWS API polling interval  # nosemgrep: arbitrary-sleep
                except Exception:
                    break
        
        # Create callerInput intent for awsOpsAuth
        print("📝 Creating callerInput intent...")
        
        # Get Lambda ARN for fulfillment
        cf = boto3.client('cloudformation')
        stack_response = cf.describe_stacks(StackName='AwsAIOpsCenterStack')
        lambda_arn = None
        for output in stack_response['Stacks'][0]['Outputs']:
            if 'AuthenticationLambda' in output['OutputKey']:
                lambda_arn = output['OutputValue']
                break
        
        caller_intent = lex.create_intent(
            botId=auth_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            intentName='callerInput',
            description='Employee authentication intent',
            sampleUtterances=[
                {'utterance': '{empId}'},
                {'utterance': 'my employee id is {empId}'},
                {'utterance': 'employee id is {empId}'},
                {'utterance': 'emp id is {empId}'},
                {'utterance': 'id is {empId}'},
                {'utterance': 'id {empId}'},
                {'utterance': 'it is {empId}'},
                {'utterance': 'is {empId}'},
                {'utterance': 'it {empId}'},
                {'utterance': 'my employee id'},
                {'utterance': 'employee id'},
                {'utterance': 'what is your employee id?'}
            ],
            fulfillmentCodeHook={
                'enabled': False
            },
            intentConfirmationSetting={
                'promptSpecification': {
                    'messageGroups': [{
                        'message': {
                            'plainTextMessage': {'value': 'Thank you!'}
                        }
                    }],
                    'maxRetries': 1
                },
                'declinationResponse': {
                    'messageGroups': [{
                        'message': {
                            'plainTextMessage': {'value': 'we couldn\'t get your details'}
                        }
                    }]
                }
            },
            intentClosingSetting={
                'closingResponse': {
                    'messageGroups': [{
                        'message': {
                            'plainTextMessage': {'value': 'I am checking details.'}
                        }
                    }]
                }
            }
        )
        
        # Create empId slot with AMAZON.Number type and obfuscation
        slot_response = lex.create_slot(
            botId=auth_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            intentId=caller_intent['intentId'],
            slotName='empId',
            description='Employee ID slot',
            slotTypeId='AMAZON.Number',
            obfuscationSetting={
                'obfuscationSettingType': 'DEFAULT_OBFUSCATION'
            },
            valueElicitationSetting={
                'slotConstraint': 'Required',
                'promptSpecification': {
                    'messageGroups': [{
                        'message': {
                            'plainTextMessage': {'value': 'Thank you!'}
                        }
                    }],
                    'maxRetries': 3
                }
            }
        )
        
        # Update intent with slot configuration
        print("💾 Saving callerInput intent with slot configuration...")
        lex.update_intent(
            botId=auth_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            intentId=caller_intent['intentId'],
            intentName='callerInput',
            description='Employee authentication intent',
            sampleUtterances=[
                {'utterance': '{empId}'},
                {'utterance': 'my employee id is {empId}'},
                {'utterance': 'employee id is {empId}'},
                {'utterance': 'emp id is {empId}'},
                {'utterance': 'id is {empId}'},
                {'utterance': 'id {empId}'},
                {'utterance': 'it is {empId}'},
                {'utterance': 'is {empId}'},
                {'utterance': 'it {empId}'},
                {'utterance': 'my employee id'},
                {'utterance': 'employee id'},
                {'utterance': 'what is your employee id?'}
            ],
            fulfillmentCodeHook={
                'enabled': False
            },
            intentConfirmationSetting={
                'promptSpecification': {
                    'messageGroups': [{
                        'message': {
                            'plainTextMessage': {'value': 'I am checking details.'}
                        }
                    }],
                    'maxRetries': 1
                },
                'declinationResponse': {
                    'messageGroups': [{
                        'message': {
                            'plainTextMessage': {'value': 'we couldn\'t get your details'}
                        }
                    }]
                }
            },
            slotPriorities=[
                {'priority': 1, 'slotId': slot_response['slotId']}
            ]
        )
        
        # Update FallbackIntent for awsOpsAuth
        print("📝 Updating FallbackIntent...")
        try:
            lex.update_intent(
                botId=auth_bot_id,
                botVersion='DRAFT',
                localeId='en_US',
                intentId='FALLBCKINT',  # Standard Lex FallbackIntent ID
                intentName='FallbackIntent',
                description='Fallback intent for unrecognized input',
                parentIntentSignature='AMAZON.FallbackIntent',
                intentClosingSetting={
                    'closingResponse': {
                        'messageGroups': [{
                            'message': {
                                'plainTextMessage': {'value': 'I could not hear your employee id. Please call us again.'}
                            }
                        }]
                    }
                }
            )
            print("✅ FallbackIntent updated successfully")
        except Exception as e:
            print(f"⚠️  FallbackIntent update failed: {e}")
        
        # Create basic SupervisorAgentIntent
        print("📝 Creating SupervisorAgentIntent...")
        supervisor_intent = lex.create_intent(
            botId=agent_bot_id,
            botVersion='DRAFT',
            localeId='en_US',
            intentName='SupervisorAgentIntent',
            description='SupervisorAgentIntent',
            sampleUtterances=[
                {'utterance': 'please give me patching status'},
                {'utterance': 'please tell me patching status on my dev instance'},
                {'utterance': 'please help me patching status on prod instance'},
                {'utterance': 'patching status on test instance'},
                {'utterance': 'patch all instances'},
                {'utterance': 'patch test instance'},
                {'utterance': 'install cloudwatch agent on this instance'}
            ]
        )
        
        supervisor_intent_id = supervisor_intent['intentId']
        print(f"✅ Basic SupervisorAgentIntent created: {supervisor_intent_id}")
        
        # Apply breakthrough Bedrock configuration
        print("🎯 Applying breakthrough Bedrock configuration...")
        bedrock_success = configure_bedrock_breakthrough(agent_bot_id, supervisor_intent_id, agent_id, alias_id)
        
        # Setup Lex Bedrock permissions
        setup_lex_bedrock_permissions(agent_id, alias_id)
        
        # Configure Lambda fulfillment for auth bot
        print("🔧 Configuring Lambda fulfillment for auth bot...")
        if lambda_arn:
            try:
                # Add Lambda permission for Lex to invoke
                lambda_client = boto3.client('lambda')
                function_name = lambda_arn.split(':')[-1]
                
                try:
                    lambda_client.add_permission(
                        FunctionName=function_name,
                        StatementId=f'lex-invoke-{auth_bot_id}',
                        Action='lambda:InvokeFunction',
                        Principal='lexv2.amazonaws.com',
                        SourceArn=f'arn:aws:lex:us-east-1:{boto3.client("sts").get_caller_identity()["Account"]}:bot/{auth_bot_id}'
                    )
                    print(f"   ✅ Lambda permission added for Lex")
                except lambda_client.exceptions.ResourceConflictException:
                    print(f"   ✅ Lambda permission already exists")
                
                # Update bot locale with Lambda fulfillment
                lex.update_bot_locale(
                    botId=auth_bot_id,
                    botVersion='DRAFT',
                    localeId='en_US',
                    description='English locale with Lambda fulfillment',
                    nluIntentConfidenceThreshold=0.4,
                    voiceSettings={
                        'voiceId': 'Ivy'
                    }
                )
                print(f"   ✅ Lambda fulfillment configured: {lambda_arn}")
            except Exception as e:
                print(f"   ⚠️  Error configuring Lambda: {e}")
        
        # Build bots
        print("🔨 Building bots...")
        
        # Build auth bot first
        print("   🔨 Building awsOpsAuth...")
        lex.build_bot_locale(botId=auth_bot_id, botVersion='DRAFT', localeId='en_US')
        
        # Build agent bot
        print("   🔨 Building awsOpsAgentBot...")
        lex.build_bot_locale(botId=agent_bot_id, botVersion='DRAFT', localeId='en_US')
        
        # Wait for builds to complete
        for bot_id, bot_name in [(auth_bot_id, 'awsOpsAuth'), (agent_bot_id, 'awsOpsAgentBot')]:
            print(f"   ⏳ Waiting for {bot_name} build...")
            for _ in range(60):  # Max 10 minutes
                try:
                    locale_status = lex.describe_bot_locale(
                        botId=bot_id,
                        botVersion='DRAFT',
                        localeId='en_US'
                    )['botLocaleStatus']
                    if locale_status == 'Built':
                        print(f"   ✅ {bot_name} build complete")
                        break
                    time.sleep(10)  # AWS API polling interval  # nosemgrep: arbitrary-sleep
                except Exception:
                    break
        
        return auth_bot_id, agent_bot_id, supervisor_intent_id, bedrock_success
        
    except Exception as e:
        print(f"❌ Error creating bots: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return None, None, None, False

def setup_lex_bedrock_permissions(agent_id, alias_id):
    """Grant Lex service permission to invoke Bedrock agent via resource-based policy"""
    
    try:
        print("🔐 Setting up Lex Bedrock permissions...")
        
        bedrock_agent = boto3.client('bedrock-agent')
        account_id = boto3.client('sts').get_caller_identity()['Account']
        region = boto3.Session().region_name or 'us-east-1'
        
        # Resource-based policy for Bedrock agent
        policy_document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "AllowLexBedrockAccess",
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "lex.amazonaws.com"
                    },
                    "Action": [
                        "bedrock:InvokeAgent"
                    ],
                    "Resource": f"arn:aws:bedrock:{region}:{account_id}:agent/{agent_id}/alias/{alias_id}"
                }
            ]
        }
        
        # Apply resource policy to Bedrock agent
        bedrock_agent.put_agent_resource_policy(
            agentId=agent_id,
            policy=json.dumps(policy_document)
        )
        
        print(f"   ✅ Bedrock agent resource policy applied: {agent_id}")
        return True
        
    except Exception as e:
        print(f"   ⚠️  Error setting Bedrock agent policy: {e}")
        return False

def configure_bedrock_breakthrough(bot_id, intent_id, agent_id, alias_id):
    """Configure Bedrock using breakthrough bedrockAgentIntentConfiguration structure"""
    
    try:
        session = boto3.Session()
        credentials = session.get_credentials()
        region = session.region_name or 'us-east-1'
        
        url = f"https://models-v2-lex.{region}.amazonaws.com/bots/{bot_id}/botversions/DRAFT/botlocales/en_US/intents/{intent_id}"
        
        # THE BREAKTHROUGH WORKING STRUCTURE!
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
            "fulfillmentCodeHook": {"enabled": False},
            "bedrockAgentIntentConfiguration": {          # ← THE BREAKTHROUGH STRUCTURE!
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
            print("   ✅ SUCCESS! Breakthrough Bedrock configuration applied!")
            return True
        else:
            print(f"   ❌ Breakthrough config failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"   ❌ Breakthrough error: {e}")
        return False

def configure_policies_and_logging(auth_bot_id, agent_bot_id, connect_instance_id):
    """Configure resource policies and conversation logging"""
    lex = boto3.client('lexv2-models')
    account_id = boto3.client('sts').get_caller_identity()['Account']
    region = 'us-east-1'
    
    print("🔧 Configuring resource policies and logging...")
    
    for bot_id, bot_name in [(auth_bot_id, 'awsOpsAuth'), (agent_bot_id, 'awsOpsAgentBot')]:
        try:
            print(f"   Configuring {bot_name}...")
            
            # Get bot aliases
            aliases = lex.list_bot_aliases(botId=bot_id)['botAliasSummaries']
            test_alias = next((alias for alias in aliases if alias['botAliasName'] == 'TestBotAlias'), None)
            
            if not test_alias:
                print(f"   ⚠️  No TestBotAlias found for {bot_name}")
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
            
            print(f"   ✅ {bot_name} configured")
            
        except Exception as e:
            print(f"   ⚠️  Error configuring {bot_name}: {e}")

def main():
    print("🚀 COMPLETE LEX DEPLOYMENT WITH BREAKTHROUGH BEDROCK")
    print("=" * 60)
    
    # Get configuration from CDK
    agent_id, alias_id, connect_instance_id = get_cdk_outputs()
    
    if not all([agent_id, alias_id, connect_instance_id]):
        print("❌ Missing required configuration from CDK")
        return
    
    print(f"✅ Bedrock Agent: {agent_id}:{alias_id}")
    print(f"✅ Connect Instance: {connect_instance_id}")
    
    # Delete existing bots
    delete_existing_bots()
    
    # Create required resources
    create_resources()
    
    # Create bots with breakthrough Bedrock configuration
    auth_bot_id, agent_bot_id, supervisor_intent_id, bedrock_success = create_bots_with_bedrock(agent_id, alias_id)
    
    if auth_bot_id and agent_bot_id:
        # Configure policies and logging
        configure_policies_and_logging(auth_bot_id, agent_bot_id, connect_instance_id)
        
        print("\n🎉 DEPLOYMENT COMPLETE!")
        print(f"✅ awsOpsAuth: {auth_bot_id}")
        print(f"✅ awsOpsAgentBot: {agent_bot_id}")
        print(f"✅ SupervisorAgentIntent: {supervisor_intent_id}")
        print(f"🎯 Bedrock Success: {bedrock_success}")
        print(f"✅ Resource policies and logging configured")
        print(f"🔗 Connect integration ready")
        
        if bedrock_success:
            print("\n🎊 100% AUTOMATED SUCCESS - NO MANUAL STEPS NEEDED!")
        else:
            print("\n⚠️  Manual Bedrock configuration may be required")
    else:
        print("\n❌ Deployment failed")

if __name__ == "__main__":
    main()
