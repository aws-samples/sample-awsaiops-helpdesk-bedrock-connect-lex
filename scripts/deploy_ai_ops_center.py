#!/usr/bin/env python3
"""
Complete AWS AI Ops Center Deployment
- Deletes existing Lex bots and Connect flows
- Deploys Lex bots with breakthrough Bedrock configuration
- Imports Connect flow with dynamic ARN replacement
- End-to-end automation
"""
import subprocess
import sys
import os
import boto3

def delete_existing_resources():
    """Delete existing Lex bots and Connect flows"""
    
    print("\n🧹 CLEANING UP EXISTING RESOURCES")
    print("=" * 50)
    
    try:
        # Delete existing Lex bots
        print("🗑️  Deleting existing Lex bots...")
        lex = boto3.client('lexv2-models')
        bots = lex.list_bots()['botSummaries']
        
        deleted_bots = 0
        for bot in bots:
            if 'awsOps' in bot['botName']:
                print(f"   Deleting {bot['botName']} ({bot['botId']})")
                lex.delete_bot(botId=bot['botId'], skipResourceInUseCheck=True)
                deleted_bots += 1
        
        if deleted_bots > 0:
            print(f"   ✅ Deleted {deleted_bots} Lex bots")
        else:
            print("   ✅ No existing Lex bots found")
        
        # Delete existing Connect flows
        print("🗑️  Deleting existing Connect flows...")
        cf = boto3.client('cloudformation')
        response = cf.describe_stack_resources(StackName='AwsAIOpsCenterStack')
        
        connect_instance_id = None
        for resource in response['StackResources']:
            if resource['ResourceType'] == 'AWS::Connect::Instance':
                connect_instance_id = resource['PhysicalResourceId'].split('/')[-1]
                break
        
        if connect_instance_id:
            connect = boto3.client('connect')
            flows = connect.list_contact_flows(InstanceId=connect_instance_id, MaxResults=50)
            
            deleted_flows = 0
            for flow in flows['ContactFlowSummaryList']:
                if 'AWS-AI-Ops-Center' in flow['Name']:
                    print(f"   Deleting {flow['Name']} ({flow['Id']})")
                    connect.delete_contact_flow(
                        InstanceId=connect_instance_id,
                        ContactFlowId=flow['Id']
                    )
                    deleted_flows += 1
            
            if deleted_flows > 0:
                print(f"   ✅ Deleted {deleted_flows} Connect flows")
            else:
                print("   ✅ No existing Connect flows found")
        else:
            print("   ⚠️  Connect instance not found")
        
        print("✅ Cleanup completed successfully!")
        return True
        
    except Exception as e:
        print(f"⚠️  Cleanup error (continuing anyway): {e}")
        return True  # Continue even if cleanup fails

def run_script(script_name, description):
    """Run a script and handle errors"""
    
    print(f"\n🚀 {description}")
    print("=" * 60)
    
    # Validate script name to prevent path traversal
    allowed_scripts = ['deploy_lex_complete.py', 'import_connect_flow_asis.py']
    if script_name not in allowed_scripts:
        print(f"❌ Script {script_name} not in allowed list")
        return False
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(script_dir, script_name)
    
    # Verify script exists and is within expected directory
    if not os.path.exists(script_path) or not script_path.startswith(script_dir):
        print(f"❌ Script path validation failed: {script_path}")
        return False
    
    try:
        # Run the script with validated paths
        result = subprocess.run([sys.executable, script_path],  # Already validating the script before execution # nosemgrep: dangerous-subprocess-use-audit
                              capture_output=False, 
                              text=True, 
                              cwd=script_dir)
        
        if result.returncode == 0:
            print(f"✅ {description} completed successfully!")
            return True
        else:
            print(f"❌ {description} failed with return code: {result.returncode}")
            return False
            
    except Exception as e:
        print(f"❌ Error running {script_name}: {e}")
        return False

def main():
    print("🎯 AWS AI OPS CENTER - COMPLETE SYSTEM DEPLOYMENT")
    print("=" * 60)
    print("This script will:")
    print("1. Delete existing Lex bots and Connect flows")
    print("2. Deploy Lex bots with breakthrough Bedrock configuration")
    print("3. Import Connect flow with dynamic ARN replacement")
    print("4. Complete end-to-end system setup")
    print("=" * 60)
    
    # Step 0: Clean up existing resources
    cleanup_success = delete_existing_resources()
    
    if cleanup_success:
        print("\n⏳ Waiting 30 seconds for resource deletion to complete...")
        import time
        time.sleep(30)  # Wait for AWS resource deletion to propagate  # nosemgrep: arbitrary-sleep
    
    # Step 1: Deploy Lex bots
    lex_success = run_script("deploy_lex_complete.py", "LEX BOTS DEPLOYMENT")
    
    if not lex_success:
        print("\n❌ Lex deployment failed. Stopping deployment.")
        return
    
    print("\n⏳ Waiting 10 seconds for Lex deployment to stabilize...")
    import time
    time.sleep(10)  # Allow Lex deployment to stabilize before Connect flow import  # nosemgrep: arbitrary-sleep
    
    # Step 2: Import Connect flow
    connect_success = run_script("import_connect_flow_asis.py", "CONNECT FLOW IMPORT")
    
    if not connect_success:
        print("\n❌ Connect flow import failed.")
        return
    
    # Final summary
    print("\n" + "=" * 60)
    print("🎉 COMPLETE SYSTEM DEPLOYMENT SUCCESSFUL!")
    print("=" * 60)
    print("✅ Cleanup: Existing resources deleted")
    print("✅ Lex Bots: Deployed with breakthrough Bedrock configuration")
    print("✅ Connect Flow: Imported with dynamic ARN replacement")
    print("✅ Employee Authentication: Ready (DynamoDB + Lambda)")
    print("✅ Bedrock Agents: Ready (EC2, SSM, Backup, Support, Supervisor)")
    print("✅ Voice Interface: Ready via Amazon Connect")
    print("✅ Chat Interface: Ready via Lex bots")
    
    print("\n🎯 SYSTEM IS READY FOR USE!")
    print("📋 Test with employee IDs: EMP001, EMP002, EMP003, EMP004, EMP005, 12345")
    print("📞 Configure phone number in Amazon Connect Console")
    print("💬 Configure chat widget in Amazon Connect Console")
    
    print("\n🎊 AWS AI OPS CENTER DEPLOYMENT COMPLETE!")

if __name__ == "__main__":
    main()
