from aws_cdk import Stack, Aws, Duration, RemovalPolicy, Aspects, CfnOutput
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_kms as kms
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import custom_resources as cr
from aws_cdk.aws_lambda import Runtime, LayerVersion, Tracing, Function, Code
from aws_ai_ops_center.connect_kinesis import ConnectResources
from aws_cdk.aws_bedrock import CfnAgent, CfnAgentAlias
from constructs import Construct
from cdk_nag import AwsSolutionsChecks, NagSuppressions
from cdklabs.generative_ai_cdk_constructs.bedrock import (
    ActionGroupExecutor,
    Agent,
    AgentActionGroup,
    ApiSchema,
    BedrockFoundationModel,
    CrossRegionInferenceProfile,
    CrossRegionInferenceProfileRegion,
    AgentCollaboratorType,
    AgentCollaborator,
    AgentAlias,
    Guardrail,
    ContentFilterType,
    ContentFilterStrength,
    Topic,
)
import os
import json


class AwsAIOpsCenterStack(Stack):
    def update_resource_config(self,change_type,resource_node,property_name,instance,value):
        if change_type == "Property":
            resource = [child for child in resource_node.node.children if isinstance(child, instance)][0]
            resource.add_override(f"Properties.{property_name}", value)
        elif change_type == "ResourceName":
            print(f"ResourceName selected {value}")
            resource = [child for child in resource_node.node.children if isinstance(child, instance)][0]
            resource.override_logical_id(value)
    
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        cris = CrossRegionInferenceProfile.from_config(
            geo_region=CrossRegionInferenceProfileRegion.US,
            model=BedrockFoundationModel.ANTHROPIC_CLAUDE_3_7_SONNET_V1_0,
        )

        powertools_layer = LayerVersion.from_layer_version_arn(
            self,
            "LambdaPowertoolsPythonLayer",
            f"arn:aws:lambda:{Aws.REGION}:017000801446:layer:AWSLambdaPowertoolsPythonV3-python312-x86_64:4",
        )

        # ============================================================
        # KMS Key for Lambda and DynamoDB encryption
        # ============================================================
        ops_kms_key = kms.Key(
            self,
            "OpsKMSKey",
            description="KMS Key for AI Ops Center resources",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY,
        )
        ops_kms_key.add_alias("alias/ai-ops-center-key")

        # ============================================================
        # Bedrock Model Invocation Logging
        # ============================================================
        bedrock_log_group = logs.LogGroup(
            self,
            "BedrockInvocationLogGroup",
            log_group_name="/aws/bedrock/model-invocations",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
            encryption_key=ops_kms_key,
        )

        # IAM role for Bedrock logging
        bedrock_logging_role = iam.Role(
            self,
            "BedrockLoggingRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        )
        bedrock_log_group.grant_write(bedrock_logging_role)

        # Bedrock Model Invocation Logging Configuration (account-level)
        bedrock_logging_config = cr.AwsCustomResource(
            self,
            "BedrockLoggingConfig",
            on_create=cr.AwsSdkCall(
                service="Bedrock",
                action="putModelInvocationLoggingConfiguration",
                parameters={
                    "loggingConfig": {
                        "cloudWatchConfig": {
                            "logGroupName": bedrock_log_group.log_group_name,
                            "roleArn": bedrock_logging_role.role_arn,
                            "largeDataDeliveryS3Config": {
                                "bucketName": "",  # Optional S3 for large payloads
                            },
                        },
                        "textDataDeliveryEnabled": True,
                        "imageDataDeliveryEnabled": False,
                        "embeddingDataDeliveryEnabled": False,
                    }
                },
                physical_resource_id=cr.PhysicalResourceId.of("bedrock-logging-config"),
            ),
            on_delete=cr.AwsSdkCall(
                service="Bedrock",
                action="deleteModelInvocationLoggingConfiguration",
                parameters={},
            ),
            policy=cr.AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    actions=[
                        "bedrock:PutModelInvocationLoggingConfiguration",
                        "bedrock:DeleteModelInvocationLoggingConfiguration",
                    ],
                    resources=["*"],
                ),
                iam.PolicyStatement(
                    actions=["iam:PassRole"],
                    resources=[bedrock_logging_role.role_arn],
                ),
            ]),
        )

        # ============================================================
        # Basic Bedrock Guardrail
        # ============================================================
        guardrail = Guardrail(
            self,
            "OpsGuardrail",
            name="ai-ops-guardrail",
            description="Basic guardrail for AI Ops Center agents",
            blocked_input_messaging="Your request contains content that is not allowed.",
            blocked_outputs_messaging="The response was blocked due to content policy.",
            kms_key=ops_kms_key,
        )

        # Add content filters for harmful content
        guardrail.add_content_filter(
            type=ContentFilterType.HATE,
            input_strength=ContentFilterStrength.HIGH,
            output_strength=ContentFilterStrength.HIGH,
        )
        guardrail.add_content_filter(
            type=ContentFilterType.INSULTS,
            input_strength=ContentFilterStrength.HIGH,
            output_strength=ContentFilterStrength.HIGH,
        )
        guardrail.add_content_filter(
            type=ContentFilterType.SEXUAL,
            input_strength=ContentFilterStrength.HIGH,
            output_strength=ContentFilterStrength.HIGH,
        )
        guardrail.add_content_filter(
            type=ContentFilterType.VIOLENCE,
            input_strength=ContentFilterStrength.HIGH,
            output_strength=ContentFilterStrength.HIGH,
        )
        guardrail.add_content_filter(
            type=ContentFilterType.MISCONDUCT,
            input_strength=ContentFilterStrength.MEDIUM,
            output_strength=ContentFilterStrength.MEDIUM,
        )

        # Add denied topic using predefined topic
        guardrail.add_denied_topic_filter(Topic.FINANCIAL_ADVICE)

        guardrail_version = guardrail.create_version("v1")

        def read_instruction(file_path: str) -> str:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()

        ec2_instruction = read_instruction(
            "lambda/instructions/ec2_agent_instruction.txt"
        )
        ssm_instruction = read_instruction(
            "lambda/instructions/ssm_agent_instruction.txt"
        )
        backup_instruction = read_instruction(
            "lambda/instructions/backup_agent_instruction.txt"
        )
        support_instruction = read_instruction(
            "lambda/instructions/support_agent_instruction.txt"
        )
        supervisor_instruction = read_instruction(
            "lambda/instructions/supervisor_agent_instruction.txt"
        )

        # IAM roles per Lambda with least-privilege policies
        ec2_lambda_role = iam.Role(
            self,
            "EC2LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
            inline_policies={
                "EC2ReadAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "ec2:DescribeInstances",
                                "ec2:DescribeInstanceStatus",
                                "ec2:DescribeVolumes",
                                "ec2:DescribeNetworkInterfaces",
                                "ec2:DescribeSecurityGroups",
                                "ec2:DescribeSubnets",
                                "ec2:DescribeVpcs",
                                "ec2:DescribeTags",
                            ],
                            resources=["*"],  # EC2 Describe actions require "*"
                        )
                    ]
                ),
                "EC2InstanceManagement": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "ec2:StartInstances",
                                "ec2:StopInstances",
                                "ec2:RebootInstances",
                            ],
                            resources=[f"arn:aws:ec2:{Aws.REGION}:{Aws.ACCOUNT_ID}:instance/*"],
                            conditions={
                                "StringEquals": {
                                    "aws:ResourceTag/ManagedByOpsCenter": "true"
                                }
                            },
                        )
                    ]
                )
            },
        )

        ssm_lambda_role = iam.Role(
            self,
            "SSMLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
            inline_policies={
                "SSMAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "ssm:SendCommand",
                                "ssm:GetCommandInvocation",
                                "ssm:ListCommands",
                                "ssm:ListCommandInvocations",
                                "ssm:DescribeDocument",
                                "ssm:GetDocument",
                                "ssm:ListDocuments",
                                "ssm:DescribePatchBaselines",
                                "ssm:GetPatchBaseline",
                                "ssm:CreatePatchBaseline",
                                "ssm:UpdatePatchBaseline",
                                "ssm:RegisterPatchBaselineForPatchGroup",
                                "ssm:DescribeInstanceInformation",
                            ],
                            resources=["*"],  # SSM requires "*" for most operations
                        )
                    ]
                )
            },
        )

        backup_lambda_role = iam.Role(
            self,
            "BackupLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
            inline_policies={
                "BackupAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "backup:CreateBackupPlan",
                                "backup:DeleteBackupPlan",
                                "backup:DescribeBackupPlan",
                                "backup:GetBackupPlan",
                                "backup:ListBackupPlans",
                                "backup:ListBackupJobs",
                                "backup:StartBackupJob",
                                "backup:CreateBackupSelection",
                            ],
                            resources=[f"arn:aws:backup:{Aws.REGION}:{Aws.ACCOUNT_ID}:backup-plan:*"],
                        ),
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "backup:ListBackupVaults",
                                "backup:DescribeBackupVault",
                            ],
                            resources=[f"arn:aws:backup:{Aws.REGION}:{Aws.ACCOUNT_ID}:backup-vault:*"],
                        ),
                    ]
                )
            },
        )

        # Support Lambda Role with AWS Support API access
        support_lambda_role = iam.Role(
            self,
            "SupportLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
            inline_policies={
                "SupportAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "support:CreateCase",
                                "support:DescribeCases",
                                "support:AddCommunicationToCase",
                                "support:ResolveCase",
                                "support:DescribeServices",
                                "support:DescribeSeverityLevels",
                            ],
                            resources=["*"],  # Support API requires "*"
                        )
                    ]
                ),
                "CloudWatchLogsQuery": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "logs:StartQuery",
                                "logs:GetQueryResults",
                                "logs:DescribeLogGroups",
                                "logs:DescribeLogStreams",
                            ],
                            resources=[f"arn:aws:logs:{Aws.REGION}:{Aws.ACCOUNT_ID}:log-group:*"],
                        )
                    ]
                )
            },
        )

        # Lambda Functions
        get_ec2_details_lambda = Function(
            self,
            "GetEC2DetailsLambda",
            runtime=Runtime.PYTHON_3_12,
            handler="lambda_handler.lambda_handler",
            code=Code.from_asset("lambda/ec2_agent_lambda/build"),
            role=ec2_lambda_role,
            memory_size=256,
            timeout=Duration.seconds(120),
            tracing=Tracing.ACTIVE,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        execute_ssm_document_lambda = Function(
            self,
            "ExecuteSSMDocumentLambda",
            runtime=Runtime.PYTHON_3_12,
            handler="lambda_handler.lambda_handler",
            code=Code.from_asset("lambda/ssm_agent_lambda/build"),
            role=ssm_lambda_role,
            memory_size=256,
            timeout=Duration.seconds(120),
            tracing=Tracing.ACTIVE,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        backup_agent_lambda = Function(
            self,
            "BackupAgentLambda",
            runtime=Runtime.PYTHON_3_12,
            handler="lambda_handler.lambda_handler",
            code=Code.from_asset("lambda/backup_agent_lambda/build"),
            role=backup_lambda_role,
            memory_size=256,
            timeout=Duration.seconds(120),
            tracing=Tracing.ACTIVE,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        
        support_agent_lambda = Function(
            self,
            "SupportAgentLambda",
            runtime=Runtime.PYTHON_3_12,
            handler="lambda_handler.lambda_handler",
            code=Code.from_asset("lambda/support_agent_lambda/build"),
            role=support_lambda_role,
            memory_size=256,
            timeout=Duration.seconds(120),
            tracing=Tracing.ACTIVE,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # Add Powertools layer to the Lambda functions
        get_ec2_details_lambda.add_layers(powertools_layer)
        execute_ssm_document_lambda.add_layers(powertools_layer)
        backup_agent_lambda.add_layers(powertools_layer)
        support_agent_lambda.add_layers(powertools_layer)

        # DynamoDB Table for Employee Authentication
        employee_table = dynamodb.Table(
            self,
            "EmployeeTable",
            table_name="employee-authentication",
            partition_key=dynamodb.Attribute(
                name="empId",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            point_in_time_recovery=True
        )

        # Authentication Lambda Role
        auth_lambda_role = iam.Role(
            self,
            "AuthLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ]
        )

        # Grant DynamoDB permissions to auth Lambda
        employee_table.grant_read_data(auth_lambda_role)

        # Authentication Lambda Function
        auth_lambda = Function(
            self,
            "AuthenticationLambda",
            runtime=Runtime.PYTHON_3_12,
            handler="lambda_handler.lambda_handler",
            code=Code.from_asset("lambda/auth_lambda"),
            role=auth_lambda_role,
            memory_size=256,
            timeout=Duration.seconds(30),
            tracing=Tracing.ACTIVE,
            log_retention=logs.RetentionDays.ONE_WEEK,
            environment={
                "EMPLOYEE_TABLE_NAME": employee_table.table_name
            }
        )

        # Add Powertools layer to auth Lambda
        auth_lambda.add_layers(powertools_layer)

        # Employee Data Population Lambda
        populate_data_lambda = Function(
            self,
            "PopulateEmployeeDataLambda",
            runtime=Runtime.PYTHON_3_12,
            handler="index.lambda_handler",
            code=Code.from_inline("""
import json
import boto3
import cfnresponse

def lambda_handler(event, context):
    try:
        if event['RequestType'] == 'Create':
            table_name = event['ResourceProperties']['TableName']
            
            employees = [
                {'empId': 'EMP001', 'name': 'John Smith', 'department': 'IT Operations', 'role': 'Senior DevOps Engineer', 'email': 'john.smith@company.com'},
                {'empId': 'EMP002', 'name': 'Sarah Johnson', 'department': 'Cloud Infrastructure', 'role': 'Cloud Architect', 'email': 'sarah.johnson@company.com'},
                {'empId': 'EMP003', 'name': 'Mike Davis', 'department': 'Security', 'role': 'Security Engineer', 'email': 'mike.davis@company.com'},
                {'empId': 'EMP004', 'name': 'Lisa Chen', 'department': 'Platform Engineering', 'role': 'Platform Engineer', 'email': 'lisa.chen@company.com'},
                {'empId': 'EMP005', 'name': 'David Wilson', 'department': 'Site Reliability', 'role': 'SRE Manager', 'email': 'david.wilson@company.com'},
                {'empId': '12345', 'name': 'Test User', 'department': 'Testing', 'role': 'Test Engineer', 'email': 'test.user@company.com'}
            ]
            
            dynamodb = boto3.resource('dynamodb')
            table = dynamodb.Table(table_name)
            
            for employee in employees:
                table.put_item(Item=employee)
            
            print(f"Successfully populated {len(employees)} employees")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {'Message': f'Populated {len(employees)} employees'})
        else:
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {'Message': 'No action required'})
            
    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {'Message': str(e)})
"""),
            memory_size=256,
            timeout=Duration.seconds(60),
            tracing=Tracing.ACTIVE,
            log_retention=logs.RetentionDays.ONE_WEEK
        )

        # Grant DynamoDB write permissions to populate Lambda
        employee_table.grant_write_data(populate_data_lambda)

        # Custom resource to populate employee data
        populate_data_trigger = cr.AwsCustomResource(
            self,
            "PopulateEmployeeDataTrigger",
            on_create=cr.AwsSdkCall(
                service="lambda",
                action="invoke",
                parameters={
                    "FunctionName": populate_data_lambda.function_name,
                    "Payload": json.dumps({
                        "RequestType": "Create",
                        "ResourceProperties": {
                            "TableName": employee_table.table_name
                        }
                    })
                },
                physical_resource_id=cr.PhysicalResourceId.of("employee-data-population")
            ),
            policy=cr.AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["lambda:InvokeFunction"],
                    resources=[populate_data_lambda.function_arn]
                )
            ])
        )

        # Ensure data population happens after table is created
        populate_data_trigger.node.add_dependency(employee_table)

        # Agents with Guardrail configuration
        ec2_agent = Agent(
            self,
            "EC2Agent",
            name="EC2Agent",
            description="Handles EC2-related queries and actions",
            foundation_model=cris,
            instruction=ec2_instruction,
            user_input_enabled=True,
            should_prepare_agent=True,
            guardrail=guardrail,
        )
        
        self.update_resource_config("Property",ec2_agent,"MemoryConfiguration",CfnAgent,{
            "EnabledMemoryTypes" : ["SESSION_SUMMARY"],
            "SessionSummaryConfiguration": {
                "MaxRecentSessions": 10
            },
            "StorageDays" : 10
        })

        ssm_agent = Agent(
            self,
            "SSMAgent",
            name="SSMAgent",
            description="Handles SSM-related queries and automation",
            foundation_model=cris,
            instruction=ssm_instruction,
            user_input_enabled=True,
            should_prepare_agent=True,
            guardrail=guardrail,
        )
        self.update_resource_config("Property",ssm_agent,"MemoryConfiguration",CfnAgent,{
            "EnabledMemoryTypes" : ["SESSION_SUMMARY"],
            "SessionSummaryConfiguration": {
                "MaxRecentSessions": 10
            },
            "StorageDays" : 10
        })

        backup_agent = Agent(
            self,
            "BackupAgent",
            name="BackupAgent",
            description="Handles AWS Backup plans and resource assignments",
            foundation_model=cris,
            instruction=backup_instruction,
            user_input_enabled=True,
            should_prepare_agent=True,
            guardrail=guardrail,
        )
        
        self.update_resource_config("Property",backup_agent,"MemoryConfiguration",CfnAgent,{
            "EnabledMemoryTypes" : ["SESSION_SUMMARY"],
            "SessionSummaryConfiguration": {
                "MaxRecentSessions": 10
            },
            "StorageDays" : 10
        })
        
        support_agent = Agent(
            self,
            "SupportAgent",
            name="SupportAgent",
            description="Creates and manages AWS Support cases for issues",
            foundation_model=cris,
            instruction=support_instruction,
            user_input_enabled=True,
            should_prepare_agent=True,
            guardrail=guardrail,
        )
        
        self.update_resource_config("Property",support_agent,"MemoryConfiguration",CfnAgent,{
            "EnabledMemoryTypes" : ["SESSION_SUMMARY"],
            "SessionSummaryConfiguration": {
                "MaxRecentSessions": 10
            },
            "StorageDays" : 10
        })

        # Action Groups
        ec2_action_group = AgentActionGroup(
            name="EC2ActionGroup",
            description="Handles EC2 queries and actions",
            executor=ActionGroupExecutor.fromlambda_function(get_ec2_details_lambda),
            enabled=True,
            api_schema=ApiSchema.from_local_asset(
                os.path.abspath("lambda/schemas/ec2_openapi.yaml")
            ),
        )
        ec2_agent.add_action_group(ec2_action_group)

        ssm_action_group = AgentActionGroup(
            name="SSMActionGroup",
            description="Handles SSM document execution",
            executor=ActionGroupExecutor.fromlambda_function(
                execute_ssm_document_lambda
            ),
            enabled=True,
            api_schema=ApiSchema.from_local_asset(
                os.path.abspath("lambda/schemas/ssm_openapi.yaml")
            ),
        )
        ssm_agent.add_action_group(ssm_action_group)

        backup_action_group = AgentActionGroup(
            name="BackupActionGroup",
            description="Manage backup plans and assignments",
            executor=ActionGroupExecutor.fromlambda_function(backup_agent_lambda),
            enabled=True,
            api_schema=ApiSchema.from_local_asset(
                os.path.abspath("lambda/schemas/backup_openapi.yaml")
            ),
        )
        backup_agent.add_action_group(backup_action_group)
        
        support_action_group = AgentActionGroup(
            name="SupportActionGroup",
            description="Create and manage AWS Support cases",
            executor=ActionGroupExecutor.fromlambda_function(support_agent_lambda),
            enabled=True,
            api_schema=ApiSchema.from_local_asset(
                os.path.abspath("lambda/schemas/support_openapi.yaml")
            ),
        )
        support_agent.add_action_group(support_action_group)

        # Agent Alias
        ec2_agent_alias = AgentAlias(
            self,
            id="GenAIOpsAssistantEC2AgentAlias",
            agent=ec2_agent,
            alias_name="EC2AgentAlias",
        )
        
        self.update_resource_config("ResourceName",ec2_agent_alias,None,CfnAgentAlias,"GenAIOpsAssistantEC2AgentAlias")

        ssm_agent_alias = AgentAlias(
            self,
            id="GenAIOpsAssistantSSMAgentAlias",
            agent=ssm_agent,
            alias_name="SSMAgentAlias",
        )
        
        self.update_resource_config("ResourceName",ssm_agent_alias,None,CfnAgentAlias,"GenAIOpsAssistantSSMAgentAlias")

        backup_agent_alias = AgentAlias(
            self,
            id="GenAIOpsAssistantBackupAgentAlias",
            agent=backup_agent,
            alias_name="BackupAgentAlias",
        )
        self.update_resource_config("ResourceName",backup_agent_alias,None,CfnAgentAlias,"GenAIOpsAssistantBackupAgentAlias")
        
        support_agent_alias = AgentAlias(
            self,
            id="GenAIOpsAssistantSupportAgentAlias",
            agent=support_agent,
            alias_name="SupportAgentAlias",
        )
        self.update_resource_config("ResourceName",support_agent_alias,None,CfnAgentAlias,"GenAIOpsAssistantSupportAgentAlias")

        # Supervisor Agent with Guardrail
        supervisor_agent = Agent(
            self,
            "SupervisorAgent",
            name="SupervisorAgent",
            instruction=supervisor_instruction,
            description="Routes queries to the appropriate agent",
            user_input_enabled=True,
            should_prepare_agent=True,
            foundation_model=cris,
            agent_collaboration=AgentCollaboratorType.SUPERVISOR_ROUTER,
            guardrail=guardrail,
            agent_collaborators=[
                AgentCollaborator(
                    agent_alias=ec2_agent_alias,
                    collaboration_instruction="Route EC2-related queries to the EC2 agent. For listing instances without specific tags, use the /list_all_ec2_instances endpoint. Always parse JSON responses from the EC2 agent and present them in a clear, readable format (not as a table unless specifically requested).",
                    collaborator_name="EC2Agent",
                    relay_conversation_history=True,
                ),
                AgentCollaborator(
                    agent_alias=ssm_agent_alias,
                    collaboration_instruction="Route SSM-related queries to the SSM agent",
                    collaborator_name="SSMAgent",
                    relay_conversation_history=True,
                ),
                AgentCollaborator(
                    agent_alias=backup_agent_alias,
                    collaboration_instruction="Route Backup-related queries to the Backup agent",
                    collaborator_name="BackupAgent",
                    relay_conversation_history=True,
                ),
                AgentCollaborator(
                    agent_alias=support_agent_alias,
                    collaboration_instruction="Route Support case creation and management to the Support agent",
                    collaborator_name="SupportAgent",
                    relay_conversation_history=True,
                ),
            ],
        )

        # SupervisorAgent Alias (was missing!)
        supervisor_agent_alias = AgentAlias(
            self,
            id="GenAIOpsAssistantSupervisorAgentAlias",
            agent=supervisor_agent,
            alias_name="SupervisorAgentAlias",
        )
        self.update_resource_config("ResourceName", supervisor_agent_alias, None, CfnAgentAlias, "GenAIOpsAssistantSupervisorAgentAlias")

        # Initialize Connect Resources
        self.connect = ConnectResources(self)

        # Add outputs for post-deployment automation
        CfnOutput(
            self, "SupervisorAgentId",
            value=supervisor_agent.agent_id,
            description="Supervisor Agent ID"
        )
        
        CfnOutput(
            self, "SupervisorAgentAliasId", 
            value=supervisor_agent_alias.alias_id,
            description="Supervisor Agent Alias ID"
        )
        
        CfnOutput(
            self, "EmployeeTableName",
            value=employee_table.table_name,
            description="Employee Authentication DynamoDB Table Name"
        )
        
        CfnOutput(
            self, "AuthenticationLambdaArn",
            value=auth_lambda.function_arn,
            description="Authentication Lambda Function ARN"
        )
        
        CfnOutput(
            self, "GuardrailId",
            value=guardrail.guardrail_id,
            description="Bedrock Guardrail ID"
        )
        
        CfnOutput(
            self, "OpsKMSKeyArn",
            value=ops_kms_key.key_arn,
            description="KMS Key ARN for AI Ops Center"
        )
        
        # CDK-Nag suppressions for necessary exceptions
        NagSuppressions.add_resource_suppressions(
            bedrock_logging_config,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Bedrock logging configuration API requires * resource for account-level settings"
                }
            ],
            apply_to_children=True
        )
        
        # Suppress managed policy warnings and other necessary exceptions
        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "AWSLambdaBasicExecutionRole is required for Lambda CloudWatch logging"
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Bedrock foundation model ARNs require wildcards; S3 object-level access requires /*"
                },
                {
                    "id": "AwsSolutions-S1",
                    "reason": "S3 access logging can be enabled post-deployment based on requirements"
                },
                {
                    "id": "AwsSolutions-S10",
                    "reason": "SSL enforcement can be added via bucket policy post-deployment"
                },
                {
                    "id": "AwsSolutions-KDF1",
                    "reason": "Firehose encryption uses S3 destination encryption with KMS"
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": "Python 3.12 is the latest stable runtime supported by Powertools layer"
                },
            ]
        )
        
        # Apply AWS Solutions security checks to this stack
        Aspects.of(self).add(AwsSolutionsChecks())