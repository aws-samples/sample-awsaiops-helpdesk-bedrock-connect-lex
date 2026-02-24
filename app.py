#!/usr/bin/env python3
import os

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from aws_ai_ops_center.aws_ai_ops_center_stack import AwsAIOpsCenterStack


app = cdk.App()

# Deploy to us-east-1 region
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region="us-east-1"
)

stack = AwsAIOpsCenterStack(
    app, 
    "AwsAIOpsCenterStack",
    env=env,
)

# Add AWS Solutions security checks
cdk.Aspects.of(app).add(AwsSolutionsChecks())

app.synth()
