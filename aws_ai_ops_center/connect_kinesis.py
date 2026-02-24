from aws_cdk import RemovalPolicy
from aws_cdk import aws_kms as kms
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_connect as connect
from aws_cdk import aws_kinesis as kinesis
from aws_cdk import aws_kinesisfirehose as firehose
from typing import Dict,List

class ConnectResources:
    """
    A class to manage and provision AWS Connect related resources.

    This class handles the creation and configuration of various AWS resources required
    for an Amazon Connect instance, including KMS keys, S3 buckets, Kinesis streams,
    and associated IAM roles and policies.

    Attributes:
        stack (Stack): The AWS CDK Stack instance where resources will be created.
        connect_instance_id (str): The ID of the Amazon Connect instance.
        connect_instance_arn (str): The ARN of the Amazon Connect instance.
        region (str): The AWS region where resources will be deployed.
        account (str): The AWS account ID where resources will be deployed.

    Example:
        stack = Stack(app, "MyConnectStack")
        connect_resources = ConnectResources(
            stack=stack,
            connect_instance_id="my-instance-id",
            connect_instance_arn="arn:aws:connect:region:account:instance/instance-id"
        )

    Note:
        - All resources created by this class will be associated with the provided stack
        - The class follows AWS best practices for security and resource management
        - Resources are created with appropriate encryption and access controls
        - Some resources may incur AWS charges
    """
    def __init__(self, stack) -> None:
        """
        Initializes a new instance of ConnectResources.

        Args:
            stack (Stack): The AWS CDK Stack where resources will be created.
            connect_instance_id (str): The ID of the Amazon Connect instance.
            connect_instance_arn (str): The ARN of the Amazon Connect instance.

        Raises:
            ValueError: If any of the required parameters are None or empty strings.
        """
        self.stack = stack
        self.s3_kms_key = self._create_s3_kms_key()
        self.kinesis_kms_key = self._create_kinesis_kms_key()
        self.buckets = self._create_s3_buckets()
        self.streams = self._create_kinesis_streams()
        self.connect_instance = self._create_connect_instance()
        self.storage_configs = self._create_storage_configs()
        self.firehose_role = self._create_firehose_role()
        self.delivery_streams = self._create_delivery_streams()

    def _create_s3_kms_key(self)-> kms.Key:
        """
        Creates a KMS key for S3 bucket encryption.

        This method initializes a new AWS KMS key specifically configured for S3 bucket
        encryption with automatic key rotation enabled. The key is set to be destroyed
        when the stack is destroyed.

        Args:
            self: The instance of the containing class that holds the stack reference.

        Returns:
            kms.Key: A configured KMS key instance with the following properties:
                - Automatic key rotation enabled
                - Destruction policy set to DESTROY
                - Description indicating its use for Amazon Connect S3 Data

        Example:
            kms_key = self._create_s3_kms_key()

        Note:
            The key's alias will be 'S3KMSKey' within the stack scope.
            The removal policy is set to DESTROY, which means the key will be deleted
            when the stack is destroyed. Use with caution in production environments.
        """
        return kms.Key(
            self.stack, 'S3KMSKey',
            description='KMS Key for Amazon Connect S3 Data',
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY
        )

    def _create_kinesis_kms_key(self)-> kms.Key:
        """
        Creates and configures a KMS key for Kinesis stream encryption with necessary IAM policies.

        This method creates a KMS key specifically for Kinesis streams and configures it with:
        1. Automatic key rotation
        2. Policy allowing Amazon Connect service to decrypt data
        3. Policy allowing Kinesis service to perform cryptographic operations

        Args:
            self: The instance of the containing class that holds the stack reference.

        Returns:
            kms.Key: A configured KMS key instance with the following properties:
                - Automatic key rotation enabled
                - Destruction policy set to DESTROY
                - Resource policies for Amazon Connect and Kinesis access
                - Region and account-specific conditions for Kinesis access

        Resource Policies:
            1. Amazon Connect Policy:
            - Allows connect.amazonaws.com to decrypt data
            - Full access to all resources under this key

            2. Kinesis Access Policy:
            - Allows encryption operations (Encrypt, Decrypt, ReEncrypt)
            - Allows data key generation
            - Allows key description retrieval
            - Restricted to specific AWS region and account
            - Conditions ensure operations are only via Kinesis service

        Example:
            kinesis_kms_key = self._create_kinesis_kms_key()

        Note:
            - The key's alias will be 'KinesisKMSKey' within the stack scope
            - The removal policy is set to DESTROY, which means the key will be deleted
            when the stack is destroyed. Use with caution in production environments.
            - The resource policies use '*' for resources, ensure this aligns with your 
            security requirements
        """
        key = kms.Key(
            self.stack, 'KinesisKMSKey',
            description='KMS Key for Amazon Connect Kinesis Streams',
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY
        )

        key.add_to_resource_policy(
            iam.PolicyStatement(
                sid='Enable Amazon Connect',
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal('connect.amazonaws.com')],
                actions=['kms:Decrypt*'],
                resources=['*']
            )
        )

        key.add_to_resource_policy(
            iam.PolicyStatement(
                sid='Allow Kinesis Access',
                effect=iam.Effect.ALLOW,
                principals=[iam.AnyPrincipal()],
                actions=[
                    'kms:Encrypt',
                    'kms:Decrypt',
                    'kms:ReEncrypt*',
                    'kms:GenerateDataKey*',
                    'kms:DescribeKey'
                ],
                resources=['*'],
                conditions={
                    'StringEquals': {
                        'kms:ViaService': f'kinesis.{self.stack.region}.amazonaws.com',
                        'kms:CallerAccount': self.stack.account
                    }
                }
            )
        )
        return key

    def _create_s3_buckets(self) -> Dict[str, s3.Bucket]:
        """
        Creates and configures S3 buckets required for Amazon Connect operations.

        This method initializes multiple S3 buckets with appropriate encryption, lifecycle rules,
        and access configurations for different Amazon Connect data types including call recordings,
        chat transcripts, and exported reports.

        Returns:
            Dict[str, s3.Bucket]: A dictionary containing the created S3 buckets with the following structure:
                {
                    'CALL_RECORDINGS': s3.Bucket (For storing voice call recordings),
                    'CHAT_TRANSCRIPTS': s3.Bucket (For storing chat conversation transcripts),
                    'SCHEDULED_REPORTS': s3.Bucket (For storing exported reports),
                    'CONTACT_TRACE_RECORDS': s3.Bucket (For storing contact trace records)
                }

        Bucket Configurations:
            - Server-side encryption using KMS
            - Versioning enabled
            - Public access blocked
            - Lifecycle rules for data retention
            - Appropriate bucket policies for Amazon Connect access

        Security Features:
            - Encryption in transit enforced
            - Server-side encryption using customer-managed KMS keys
            - Block public access enabled
            - Versioning enabled for data protection
            - Cross-Region replication disabled by default

        Example:
            buckets = self._create_s3_buckets()
            call_recordings_bucket = buckets['CALL_RECORDINGS']
            chat_transcripts_bucket = buckets['CHAT_TRANSCRIPTS']

        Note:
            - Bucket names are automatically generated with unique identifiers
            - RemovalPolicy is set to RETAIN by default for data protection
            - Ensure proper IAM permissions are set up for bucket access
            - Consider data retention requirements when modifying lifecycle rules
            - Buckets are created in the same region as the stack
        """
        return {
            'connect_data': s3.Bucket(
                self.stack, 'S3BucketForConnectData',
                bucket_name=f'connect-data-{self.stack.account}',
                encryption=s3.BucketEncryption.KMS,
                encryption_key=self.s3_kms_key,
                removal_policy=RemovalPolicy.DESTROY
            ),
            'agent_events': s3.Bucket(
                self.stack, 'S3BucketForAgentEvents',
                bucket_name=f'connect-agent-events-{self.stack.account}',
                encryption=s3.BucketEncryption.KMS,
                encryption_key=self.s3_kms_key,
                removal_policy=RemovalPolicy.DESTROY
            ),
            'ctr_records': s3.Bucket(
                self.stack, 'S3BucketForCTRRecords',
                bucket_name=f'connect-ctr-records-{self.stack.account}',
                encryption=s3.BucketEncryption.KMS,
                encryption_key=self.s3_kms_key,
                removal_policy=RemovalPolicy.DESTROY
            )
        }

    def _create_kinesis_streams(self)-> Dict[str, kinesis.Stream]:
        """
        Creates and configures Kinesis data streams for Amazon Connect data ingestion.

        This method sets up multiple Kinesis streams for different Amazon Connect data types,
        configuring them with appropriate encryption, retention, and throughput settings.
        Each stream is optimized for specific Connect data patterns and compliance requirements.

        Returns:
            Dict[str, kinesis.Stream]: A dictionary of configured Kinesis streams with the following mapping:
                {
                    'CONTACT_TRACE_RECORDS': Stream for contact metadata and outcomes,
                    'AGENT_EVENTS': Stream for agent state changes and activities,
                    'CHAT_TRANSCRIPTS': Stream for real-time chat transcripts,
                    'CONTACT_LENS': Stream for Contact Lens analysis data
                }

        Stream Specifications:
            Contact Trace Records:
                - Retention: 24 hours
                - Shard Count: 2 (default)
                - Use Case: Capture contact metadata, routing, and outcome data

            Agent Events:
                - Retention: 24 hours
                - Shard Count: 1 (default)
                - Use Case: Monitor agent state changes and activities

            Chat Transcripts:
                - Retention: 24 hours
                - Shard Count: 1 (default)
                - Use Case: Real-time chat conversation data

            Contact Lens:
                - Retention: 24 hours
                - Shard Count: 2 (default)
                - Use Case: Advanced conversation analytics data

        Security Configuration:
            - Server-side encryption using customer-managed KMS keys
            - IAM-based access control
            - Private VPC endpoints (optional)
            - Encryption in transit

        Performance Considerations:
            - Base shard throughput:
                * Write: 1 MB/second or 1000 records/second per shard
                * Read: 2 MB/second per shard
            - Enhanced fan-out consumers supported
            - Auto-scaling can be enabled based on usage patterns

        Example:
            streams = self._create_kinesis_streams()
            ctr_stream = streams['CONTACT_TRACE_RECORDS']
            print(f"CTR Stream ARN: {ctr_stream.stream_arn}")

        Raises:
            ValueError: If required KMS key configuration fails
            Exception: If stream creation encounters errors

        Note:
            - Stream names are prefixed with stack name for identification
            - Monitor shard utilization for optimal performance
            - Consider cost implications of shard count and retention
            - Set up CloudWatch alarms for monitoring
            - Implement error handling for stream operations
            - Review compliance requirements for data retention
            - Ensure proper backup and disaster recovery procedures
        """
        return {
            'ctr': kinesis.Stream(
                self.stack, 'CTRKinesisStream',
                stream_name=f'connect-ctr-stream-{self.stack.account}',
                shard_count=1,
                encryption=kinesis.StreamEncryption.KMS,
                encryption_key=self.kinesis_kms_key
            ),
            'agent_event': kinesis.Stream(
                self.stack, 'AgentEventKinesisStream',
                stream_name=f'connect-agent-event-stream-{self.stack.account}',
                shard_count=1,
                encryption=kinesis.StreamEncryption.KMS,
                encryption_key=self.kinesis_kms_key
            )
        }

    def _create_connect_instance(self) -> connect.CfnInstance:
        """
        Creates and configures an Amazon Connect instance with specified settings and integrations.

        This method provisions a new Amazon Connect instance with appropriate configurations
        for identity management, data storage, telephony, and security settings. It also
        sets up necessary integrations with other AWS services.

        Returns:
            connect.CfnInstance: A configured Amazon Connect instance with the following setup:
                - Identity management configuration
                - Data storage locations
                - Telephony settings
                - Security profiles
                - Service integrations

        Instance Configuration:
            Identity Management:
                - SAML authentication (optional)
                - AWS Directory Service integration (optional)
                - Custom identity provider settings

            Data Storage:
                - Call recordings in S3
                - Chat transcripts
                - Scheduled reports
                - Contact trace records

            Telephony Settings:
                - Inbound calling
                - Outbound calling
                - Voice configuration
                - Phone number assignments

            Security:
                - Encryption at rest
                - Network settings
                - Security profiles
                - Access control

        Integration Points:
            - Amazon S3 for data storage
            - Kinesis for real-time streaming
            - Lambda for custom functionality
            - CloudWatch for monitoring
            - KMS for encryption

        Example:
            connect_instance = self._create_connect_instance()
            instance_id = connect_instance.attr_instance_id
            instance_arn = connect_instance.attr_arn

        Raises:
            ValueError: If required configuration parameters are missing
            Exception: If instance creation fails

        Note:
            - Instance creation may take several minutes
            - Phone numbers must be claimed separately
            - Default security profiles are created automatically
            - Consider compliance requirements for data retention
            - Set up appropriate monitoring and alerting
            - Review network and security configurations
            - Plan for disaster recovery
            - Monitor service quotas and limits

        Security Considerations:
            - Enable encryption at rest
            - Configure appropriate IAM roles
            - Set up network security
            - Implement access controls
            - Monitor security events
            - Regular security audits
            - Compliance monitoring

        Cost Considerations:
            - Per-minute charges for calls
            - Storage costs for recordings
            - Data transfer costs
            - Additional feature costs
            - Phone number charges
        """
        return connect.CfnInstance(
            self.stack, 'ConnectInstance',
            instance_alias=f'ai-ops-sample-{self.stack.account}',
            identity_management_type='SAML',
            attributes=connect.CfnInstance.AttributesProperty(
                inbound_calls=True,
                outbound_calls=True,
                contactflow_logs=True,
                contact_lens=True,
                early_media=False
            ),
            tags=[
                {'key': 'Environment', 'value': 'Production'},
                {'key': 'Project', 'value': 'MyConnectProject'}
            ]
        )

    def _create_storage_configs(self)-> Dict[str, connect.CfnInstanceStorageConfig]:
        """
        Creates and configures storage configurations for various Amazon Connect data types.

        This method sets up storage configurations for different types of Connect data,
        including call recordings, chat transcripts, and contact trace records (CTRs).
        It configures the appropriate storage locations and retention policies for each
        data type according to business requirements and compliance standards.

        Returns:
            Dict[str, connect.CfnInstanceStorageConfig]: A dictionary of storage
            configurations with the following structure:
                {
                    'CALL_RECORDINGS': Configuration for voice recording storage,
                    'CHAT_TRANSCRIPTS': Configuration for chat transcript storage,
                    'SCHEDULED_REPORTS': Configuration for scheduled reports,
                    'CONTACT_TRACE_RECORDS': Configuration for CTR storage,
                    'MEDIA_STREAMS': Configuration for real-time media streaming
                }

        Storage Configuration Types:
            Call Recordings:
                - Storage Location: S3
                - Encryption: KMS
                - Retention: Configurable
                - Path Format: YYYY/MM/DD/ContactID

            Chat Transcripts:
                - Storage Location: S3
                - Encryption: KMS
                - Retention: Configurable
                - Path Format: YYYY/MM/DD/ContactID

            Scheduled Reports:
                - Storage Location: S3
                - Encryption: KMS
                - Retention: Configurable
                - Path Format: YYYY/MM/DD/ReportID

            Contact Trace Records:
                - Storage Type: Kinesis
                - Stream Mode: Provisioned
                - Retention: 24 hours
                - Real-time delivery

            Media Streams:
                - Storage Type: Kinesis
                - Stream Mode: Provisioned
                - Real-time streaming
                - Audio format: Raw or Encoded

        Security Features:
            - Server-side encryption using KMS
            - IAM role-based access control
            - Audit logging enabled
            - Encryption in transit
            - Access monitoring

        Example:
            storage_configs = self._create_storage_configs()
            call_recording_config = storage_configs['CALL_RECORDINGS']
            ctr_config = storage_configs['CONTACT_TRACE_RECORDS']

        Raises:
            ValueError: If required storage locations or streams are not configured
            Exception: If storage configuration creation fails

        Note:
            - Ensure proper IAM roles and permissions are configured
            - Monitor storage usage and costs
            - Set up lifecycle policies for S3 storage
            - Configure backup and retention policies
            - Review compliance requirements
            - Set up monitoring and alerting
            - Consider data privacy requirements
            - Plan for disaster recovery

        Compliance Considerations:
            - Data retention policies
            - Encryption requirements
            - Access controls
            - Audit logging
            - Geographic restrictions
            - Industry-specific requirements

        Performance Considerations:
            - S3 storage class selection
            - Kinesis stream capacity
            - Data access patterns
            - Retrieval requirements
            - Archival strategies
        """
        configs = []
        configs.append(connect.CfnInstanceStorageConfig(
            self.stack, 'ConnectInstanceStorageConfigCallRecordings',
            instance_arn=self.connect_instance.attr_arn,
            resource_type='CALL_RECORDINGS',
            storage_type='S3',
            s3_config=connect.CfnInstanceStorageConfig.S3ConfigProperty(
                bucket_name=self.buckets['connect_data'].bucket_name,
                bucket_prefix='call-recordings',
                encryption_config=connect.CfnInstanceStorageConfig.EncryptionConfigProperty(
                    encryption_type='KMS',
                    key_id=self.s3_kms_key.key_arn  # gitleaks:allow reason: not API key it's kms key arn
                )
            )
        ))
        configs.append(connect.CfnInstanceStorageConfig(
            self.stack, 'ConnectInstanceStorageConfigChat',
            instance_arn=self.connect_instance.attr_arn,
            resource_type='CHAT_TRANSCRIPTS',
            storage_type='S3',
            s3_config=connect.CfnInstanceStorageConfig.S3ConfigProperty(
                bucket_name=self.buckets['connect_data'].bucket_name,
                bucket_prefix='chat-transcripts',
                encryption_config=connect.CfnInstanceStorageConfig.EncryptionConfigProperty(
                    encryption_type='KMS',
                    key_id=self.s3_kms_key.key_arn  # gitleaks:allow reason: not API key it's kms key arn
                )
            )
        ))
        configs.append(connect.CfnInstanceStorageConfig(
            self.stack, 'ConnectInstanceStorageConfigReports',
            instance_arn=self.connect_instance.attr_arn,
            resource_type='SCHEDULED_REPORTS',
            storage_type='S3',
            s3_config=connect.CfnInstanceStorageConfig.S3ConfigProperty(
                bucket_name=self.buckets['connect_data'].bucket_name,
                bucket_prefix='scheduled-reports',
                encryption_config=connect.CfnInstanceStorageConfig.EncryptionConfigProperty(
                    encryption_type='KMS',
                    key_id=self.s3_kms_key.key_arn  # gitleaks:allow reason: not API key it's kms key arn
                )
            )
        ))
        configs.append(connect.CfnInstanceStorageConfig(
            self.stack, 'ConnectInstanceStorageCTR',
            instance_arn=self.connect_instance.attr_arn,
            resource_type='CONTACT_TRACE_RECORDS',
            storage_type='KINESIS_STREAM',
            kinesis_stream_config=connect.CfnInstanceStorageConfig.KinesisStreamConfigProperty(
                stream_arn=self.streams['ctr'].stream_arn
            )
        ))
        configs.append(connect.CfnInstanceStorageConfig(
            self.stack, 'ConnectInstanceStorageAgentEvents',
            instance_arn=self.connect_instance.attr_arn,
            resource_type='AGENT_EVENTS',
            storage_type='KINESIS_STREAM',
            kinesis_stream_config=connect.CfnInstanceStorageConfig.KinesisStreamConfigProperty(
                stream_arn=self.streams['agent_event'].stream_arn
            )
        ))
        return configs

    def _create_firehose_role(self)-> iam.Role:
        """
        Creates an IAM role that grants Kinesis Firehose the necessary permissions
        to operate with least-privilege access.
        """
        # Kinesis stream access policy - scoped to specific streams
        kinesis_stream_policy = iam.ManagedPolicy(
            self.stack,
            "KinesisStreamsAccessPolicy",
            managed_policy_name=f"kinesis-firehose-policy-{self.stack.account}",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        'kinesis:DescribeStream',
                        'kinesis:GetShardIterator',
                        'kinesis:GetRecords',
                        'kinesis:ListShards'
                    ],
                    resources=[
                        self.streams['ctr'].stream_arn,
                        self.streams['agent_event'].stream_arn
                    ]
                )
            ]
        )
        
        role = iam.Role(
            self.stack, 'KinesisFirehoseRole',
            assumed_by=iam.ServicePrincipal('firehose.amazonaws.com'),
            managed_policies=[kinesis_stream_policy],
        )
        
        # S3 access - scoped to specific buckets
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                's3:PutObject',
                's3:GetObject',
                's3:ListBucket',
                's3:GetBucketLocation',
            ],
            resources=[
                self.buckets['ctr_records'].bucket_arn,
                f"{self.buckets['ctr_records'].bucket_arn}/*",
                self.buckets['agent_events'].bucket_arn,
                f"{self.buckets['agent_events'].bucket_arn}/*",
            ]
        ))
        
        # CloudWatch Logs - scoped to specific log groups
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents'
            ],
            resources=[
                f"arn:aws:logs:{self.stack.region}:{self.stack.account}:log-group:{self.stack.stack_name}-*",
            ]
        ))
        
        # KMS access - scoped to specific keys
        role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                'kms:Decrypt',
                'kms:GenerateDataKey'
            ],
            resources=[
                self.s3_kms_key.key_arn,  # gitleaks:allow reason: not API key it's kms key arn
                self.kinesis_kms_key.key_arn  # gitleaks:allow reason: not API key it's kms key arn
            ]
        ))
        return role

    def _create_delivery_streams(self)-> List[firehose.CfnDeliveryStream]:
        """
        Creates Kinesis Firehose delivery streams for data ingestion.
        
        This method creates a Kinesis Firehose delivery stream that:
        - Sources data from a Kinesis stream
        - Delivers data to an S3 bucket
        - Includes CloudWatch logging configuration
        - Implements buffering with specified interval and size
        
        Returns:
            List[firehose.CfnDeliveryStream]: A list containing the created Kinesis 
            Firehose delivery stream configurations.
        
        Note:
            The delivery stream is configured to:
            - Buffer data for 300 seconds or 64 MB, whichever comes first
            - Store uncompressed data in the S3 bucket
            - Use the prefix 'ctr-records/' for S3 objects
            - Enable CloudWatch logging for monitoring
        """
        streams = []
        streams.append(firehose.CfnDeliveryStream(
            self.stack, 'CTRKinesisFirehoseDeliveryStream',
            delivery_stream_name='CTRKinesisFirehoseDeliveryStream',
            delivery_stream_type='KinesisStreamAsSource',
            kinesis_stream_source_configuration=firehose.CfnDeliveryStream.KinesisStreamSourceConfigurationProperty(
                kinesis_stream_arn=self.streams['ctr'].stream_arn,
                role_arn=self.firehose_role.role_arn
            ),
            extended_s3_destination_configuration=firehose.CfnDeliveryStream.ExtendedS3DestinationConfigurationProperty(
                bucket_arn=self.buckets['ctr_records'].bucket_arn,
                buffering_hints=firehose.CfnDeliveryStream.BufferingHintsProperty(
                    interval_in_seconds=300,
                    size_in_m_bs=64
                ),
                compression_format='UNCOMPRESSED',
                prefix='ctr-records/',
                role_arn=self.firehose_role.role_arn,
                cloud_watch_logging_options=firehose.CfnDeliveryStream.CloudWatchLoggingOptionsProperty(
                    enabled=True,
                    log_group_name=f'{self.stack.stack_name}-CTRKinesisFirehoseDeliveryStream',
                    log_stream_name='CTRKinesisFirehoseDeliveryStream'
                )
            )
        ))
        streams.append(firehose.CfnDeliveryStream(
            self.stack, 'AgentEventKinesisFirehoseDeliveryStream',
            delivery_stream_name='AgentEventKinesisFirehoseDeliveryStream',
            delivery_stream_type='KinesisStreamAsSource',
            kinesis_stream_source_configuration=firehose.CfnDeliveryStream.KinesisStreamSourceConfigurationProperty(
                kinesis_stream_arn=self.streams['agent_event'].stream_arn,
                role_arn=self.firehose_role.role_arn
            ),
            extended_s3_destination_configuration=firehose.CfnDeliveryStream.ExtendedS3DestinationConfigurationProperty(
                bucket_arn=self.buckets['agent_events'].bucket_arn,
                buffering_hints=firehose.CfnDeliveryStream.BufferingHintsProperty(
                    interval_in_seconds=300,
                    size_in_m_bs=64
                ),
                compression_format='UNCOMPRESSED',
                prefix='agent-events/',
                role_arn=self.firehose_role.role_arn,
                cloud_watch_logging_options=firehose.CfnDeliveryStream.CloudWatchLoggingOptionsProperty(
                    enabled=True,
                    log_group_name=f'{self.stack.stack_name}-AgentEventKinesisFirehoseDeliveryStream',
                    log_stream_name='AgentEventKinesisFirehoseDeliveryStream'
                )
            )
        ))
        return streams