from aws_cdk import (
    aws_lex as lex,
    aws_iam as iam,
    aws_logs as logs,
    aws_kms as kms,
    RemovalPolicy
)
from constructs import Construct

class LexBotConstruct(Construct):
    def __init__(self, scope: Construct, construct_id: str, encryption_key: kms.IKey = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # Create Lex service role with least-privilege
        lex_role = iam.Role(
            self, "LexServiceRole",
            assumed_by=iam.ServicePrincipal("lexv2.amazonaws.com"),
            inline_policies={
                "LexBasicPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "polly:SynthesizeSpeech",
                                "comprehend:DetectSentiment",
                            ],
                            resources=["*"],  # Polly/Comprehend require "*"
                        )
                    ]
                )
            }
        )
        
        # Create CloudWatch log group with encryption
        log_group = logs.LogGroup(
            self, "LexLogGroup",
            log_group_name="/aws/lex/awsOpsAgentBot",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
            encryption_key=encryption_key,
        )
        
        # Auth Bot
        self.auth_bot = lex.CfnBot(
            self, "AuthBot",
            bot_name="awsOpsAuth",
            role_arn=lex_role.role_arn,
            data_privacy={"ChildDirected": False},
            idle_session_ttl_in_seconds=300,
            bot_locales=[
                {
                    "localeId": "en_US",
                    "nluConfidenceThreshold": 0.4,
                    "intents": [
                        {
                            "intentName": "callerInput",
                            "description": "Caller input intent",
                            "sampleUtterances": [
                                {"utterance": "my employee id is {empId}"},
                                {"utterance": "{empId}"},
                                {"utterance": "employee id {empId}"}
                            ],
                            "slots": [
                                {
                                    "slotName": "empId",
                                    "description": "Employee ID slot",
                                    "slotTypeName": "AMAZON.AlphaNumeric",
                                    "obfuscationSetting": {
                                        "obfuscationSettingType": "DEFAULT_OBFUSCATION"
                                    },
                                    "valueElicitationSetting": {
                                        "slotConstraint": "Required",
                                        "promptSpecification": {
                                            "messageGroupsList": [
                                                {
                                                    "message": {
                                                        "plainTextMessage": {
                                                            "value": "Please provide your employee ID"
                                                        }
                                                    }
                                                }
                                            ],
                                            "maxRetries": 3
                                        }
                                    }
                                }
                            ]
                        }
                    ]
                }
            ]
        )
        
        # Agent Bot
        self.agent_bot = lex.CfnBot(
            self, "AgentBot",
            bot_name="awsOpsAgentBot",
            role_arn=lex_role.role_arn,
            data_privacy={"ChildDirected": False},
            idle_session_ttl_in_seconds=1800,
            bot_locales=[
                {
                    "localeId": "en_US",
                    "nluConfidenceThreshold": 0.4,
                    "intents": [
                        {
                            "intentName": "SupervisorAgentIntent",
                            "description": "Bedrock Agent Integration Intent",
                            "parentIntentSignature": "AMAZON.BedrockAgentIntent",
                            "sampleUtterances": [
                                {"utterance": "list all my EC2 instances"},
                                {"utterance": "patch all instances"},
                                {"utterance": "install cloudwatch agent"},
                                {"utterance": "please give me patching status"}
                            ],
                            "fulfillmentCodeHook": {"enabled": False}
                        }
                    ]
                }
            ]
        )
        
        # Bot Versions
        self.auth_bot_version = lex.CfnBotVersion(
            self, "AuthBotVersion",
            bot_id=self.auth_bot.attr_id,
            description="Production version",
            bot_version_locale_specification=[
                {
                    "localeId": "en_US",
                    "botVersionLocaleDetails": {
                        "sourceBotVersion": "DRAFT"
                    }
                }
            ]
        )
        
        self.agent_bot_version = lex.CfnBotVersion(
            self, "AgentBotVersion",
            bot_id=self.agent_bot.attr_id,
            description="Production version",
            bot_version_locale_specification=[
                {
                    "localeId": "en_US",
                    "botVersionLocaleDetails": {
                        "sourceBotVersion": "DRAFT"
                    }
                }
            ]
        )
        
        # Bot Aliases with conversation logging
        self.auth_bot_alias = lex.CfnBotAlias(
            self, "AuthBotAlias",
            bot_alias_name="TestBotAlias",
            bot_id=self.auth_bot.attr_id,
            bot_version=self.auth_bot_version.attr_bot_version,
            bot_alias_locale_settings=[
                {
                    "localeId": "en_US",
                    "botAliasLocaleSetting": {"enabled": True}
                }
            ],
            conversation_log_settings={
                "textLogSettings": [
                    {
                        "enabled": True,
                        "destination": {
                            "cloudWatch": {
                                "cloudWatchLogGroupArn": log_group.log_group_arn,
                                "logPrefix": "lex-auth"
                            }
                        }
                    }
                ]
            }
        )
        
        self.agent_bot_alias = lex.CfnBotAlias(
            self, "AgentBotAlias",
            bot_alias_name="TestBotAlias",
            bot_id=self.agent_bot.attr_id,
            bot_version=self.agent_bot_version.attr_bot_version,
            bot_alias_locale_settings=[
                {
                    "localeId": "en_US",
                    "botAliasLocaleSetting": {"enabled": True}
                }
            ],
            conversation_log_settings={
                "textLogSettings": [
                    {
                        "enabled": True,
                        "destination": {
                            "cloudWatch": {
                                "cloudWatchLogGroupArn": log_group.log_group_arn,
                                "logPrefix": "lex-agent"
                            }
                        }
                    }
                ]
            }
        )
