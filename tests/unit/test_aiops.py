import aws_cdk as cdk
from aws_cdk.assertions import Template, Match
import pytest
from aws_ai_ops_center.aws_ai_ops_center_stack import AwsAIOpsCenterStack



@pytest.fixture
def app():
    return cdk.App()

@pytest.fixture
def stack(app):
    return AwsAIOpsCenterStack(app, "test-stack")

@pytest.fixture
def template(stack):
    return Template.from_stack(stack)

def test_lambda_functions_created(template):
    template.resource_count_is("AWS::Lambda::Function", 5)
    
    # Verify Lambda functions have expected properties
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "lambda_handler.lambda_handler",
        "Runtime": "python3.12",
        "MemorySize": 256,
        "Timeout": 120,
        "TracingConfig": {
            "Mode": "Active"
        }
    })

def test_lambda_permissions_created(template):
    template.resource_count_is("AWS::Lambda::Permission", 4)
    
def test_kms_key_created(template):
    template.resource_count_is("AWS::KMS::Key", 2)   
    

def test_iam_roles_created(template):
    template.resource_count_is("AWS::IAM::Role", 11)
    
def test_iam_policies_created(template):
    template.resource_count_is("AWS::IAM::Policy", 11)
 
def test_kinesis_created(template):
    template.resource_count_is("AWS::Kinesis::Stream", 2)


def test_kinesis_created(template):
    template.resource_count_is("AWS::KinesisFirehose::DeliveryStream", 2)

def test_bedrock_agents_created(template):
    template.resource_count_is("AWS::Bedrock::Agent", 5)
    template.has_resource_properties("AWS::Bedrock::AgentAlias", {
        "AgentAliasName" : "EC2AgentAlias"
    })
    
    template.has_resource_properties("AWS::Bedrock::AgentAlias", {
        "AgentAliasName" : "SSMAgentAlias"
    })
    
    template.has_resource_properties("AWS::Bedrock::AgentAlias", {
        "AgentAliasName" : "BackupAgentAlias"
    })
    
    template.has_resource_properties("AWS::Bedrock::AgentAlias", {
        "AgentAliasName" : "SupportAgentAlias"
    })
    
    # Test agent configuration
    template.has_resource_properties("AWS::Bedrock::Agent", {
        "MemoryConfiguration": {
            "EnabledMemoryTypes": [
             "SESSION_SUMMARY"
            ],
            "SessionSummaryConfiguration": {
                "MaxRecentSessions": 10
            },
            "StorageDays": 10
        }
    })