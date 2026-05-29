# cloud-to-iac

Connects to your live AWS account, discovers what's running, and writes it all out as **Terraform HCL** or **CloudFormation YAML**. Covers 41 resource types across networking, compute, storage, databases, messaging, security, and DevOps services.

---

## Requirements

- Docker installed and running
- AWS credentials (access keys, a named profile, or an IAM role)
- The image pulled from the private registry (contact the distributor for access)

---

## Pull the image

```bash
docker pull yourusername/cloud-to-iac:latest
```

---

## Quickstart

```bash
docker run --rm \
  -e AWS_ACCESS_KEY_ID=your_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret \
  -e AWS_DEFAULT_REGION=us-east-1 \
  -v $(pwd)/output:/output \
  yourusername/cloud-to-iac:latest \
  convert --region us-east-1 --format terraform --output /output
```

Your generated files will land in `./output/` on your machine.

---

## Passing AWS credentials

There are three ways to give the container access to your AWS account. Use whichever fits your setup.

### Option 1 — Environment variables

```bash
docker run --rm \
  -e AWS_ACCESS_KEY_ID=your_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret \
  -v $(pwd)/output:/output \
  yourusername/cloud-to-iac:latest \
  convert --region us-east-1 --output /output
```

### Option 2 — Mount your AWS credentials file

If you already have profiles set up in `~/.aws`, mount the whole directory:

```bash
docker run --rm \
  -v ~/.aws:/root/.aws:ro \
  -v $(pwd)/output:/output \
  yourusername/cloud-to-iac:latest \
  convert --region us-east-1 --profile your-profile --output /output
```

### Option 3 — Cross-account role assumption

```bash
docker run --rm \
  -e AWS_ACCESS_KEY_ID=your_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret \
  -v $(pwd)/output:/output \
  yourusername/cloud-to-iac:latest \
  convert --region us-east-1 \
  --role-arn arn:aws:iam::123456789012:role/ReadOnlyRole \
  --output /output
```

When using `--role-arn` with Terraform output, the generated provider block automatically includes an `assume_role` stanza.

---

## Step-by-step usage

### Step 1 — Scan your account first

Run `scan` to see what will be discovered. It's read-only and writes no files.

```bash
docker run --rm \
  -e AWS_ACCESS_KEY_ID=your_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret \
  yourusername/cloud-to-iac:latest \
  scan --region us-east-1
```

You'll get a table showing resource counts. If something looks off, check the [IAM permissions](#required-iam-permissions) section.

### Step 2 — Generate the IaC

```bash
# Terraform
docker run --rm \
  -e AWS_ACCESS_KEY_ID=your_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret \
  -v $(pwd)/output:/output \
  yourusername/cloud-to-iac:latest \
  convert --region us-east-1 --format terraform --output /output

# CloudFormation
docker run --rm \
  -e AWS_ACCESS_KEY_ID=your_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret \
  -v $(pwd)/output:/output \
  yourusername/cloud-to-iac:latest \
  convert --region us-east-1 --format cloudformation --output /output
```

This writes two files into `./output/`:
- `main.tf` (or `template.yaml` for CloudFormation)
- `inventory.json` — a snapshot of discovered resources

### Step 3 — Review the output

Open the generated file before doing anything with it. Check that:
- Names and tags look right
- Any raw IDs (search for `"vpc-` or `"sg-`) are things you expected to fall back
- Sensitive values like RDS passwords are parameterised

### Step 4 — Import into Terraform state

The generated code doesn't automatically import your existing resources into Terraform state — you need to do that yourself.

```bash
cd output
terraform init
terraform import aws_vpc.prod vpc-0abc1234
terraform import aws_s3_bucket.my_bucket my-bucket-name
# repeat for each resource
```

Then run `terraform plan` to confirm no unintended changes before touching anything.

### Step 5 — Scan only specific resource types

Use `--resources` to skip everything you don't need:

```bash
docker run --rm \
  -e AWS_ACCESS_KEY_ID=your_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret \
  -v $(pwd)/output:/output \
  yourusername/cloud-to-iac:latest \
  convert --region us-east-1 --resources vpc,subnet,sg,ec2,s3 --output /output
```

Available filter keys:

| Key | Resource | Key | Resource |
|-----|----------|-----|----------|
| `vpc` | VPCs | `apigw` | API Gateway REST |
| `subnet` | Subnets | `httpapi` | API Gateway HTTP |
| `igw` | Internet Gateways | `cf` | CloudFront |
| `nat` | NAT Gateways | `r53` | Route 53 |
| `eip` | Elastic IPs | `acm` | ACM Certificates |
| `rt` | Route Tables | `sns` | SNS Topics |
| `sg` | Security Groups | `sqs` | SQS Queues |
| `nacl` | Network ACLs | `kinesis` | Kinesis Streams |
| `peer` | VPC Peering | `eb` | EventBridge Rules |
| `endpoint` | VPC Endpoints | `secret` | Secrets Manager |
| `ec2` | EC2 Instances | `kms` | KMS Keys |
| `lambda` | Lambda Functions | `alarm` | CloudWatch Alarms |
| `ecs` | ECS Clusters | `logs` | Log Groups |
| `ecstask` | ECS Task Definitions | `pipeline` | CodePipelines |
| `ecssvc` | ECS Services | `build` | CodeBuild |
| `eks` | EKS Clusters | `waf` | WAF Web ACLs |
| `ecr` | ECR Repositories | `iam` | IAM Roles |
| `s3` | S3 Buckets | `alb` | Load Balancers |
| `rds` | RDS Instances | `asg` | Auto Scaling Groups |
| `dynamo` | DynamoDB Tables | `cache` | ElastiCache |
| `efs` | EFS File Systems | `ebs` | EBS Volumes |

### Step 6 — Re-generate from a saved snapshot

If you already have an `inventory.json` from a previous scan, you can re-generate code without hitting AWS again:

```bash
docker run --rm \
  -v $(pwd)/output:/output \
  yourusername/cloud-to-iac:latest \
  generate /output/inventory.json --format terraform --region us-east-1 --output /output
```

Useful if you want to switch output format or retry after making changes.

### Step 7 — AI cleanup (optional)

Pass `--ai` to send the generated code through Claude for a cleanup pass — better variable names, dependency ordering, and security flags.

```bash
docker run --rm \
  -e AWS_ACCESS_KEY_ID=your_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret \
  -e ANTHROPIC_API_KEY=your_anthropic_key \
  -v $(pwd)/output:/output \
  yourusername/cloud-to-iac:latest \
  convert --region us-east-1 --ai --output /output
```

---

## CloudFormation workflow

```bash
# Validate the template
aws cloudformation validate-template \
  --template-body file://output/template.yaml

# Deploy
aws cloudformation deploy \
  --template-file output/template.yaml \
  --stack-name my-stack \
  --capabilities CAPABILITY_NAMED_IAM
```

---

## Supported resources

| Category | Resources |
|----------|-----------|
| Networking | VPC, Subnets, Internet Gateways, NAT Gateways, Elastic IPs, Route Tables, Security Groups, Network ACLs, VPC Peering, VPC Endpoints |
| Compute | EC2 Instances, Lambda Functions, ECS Clusters, ECS Task Definitions, ECS Services, EKS Clusters, ECR Repositories |
| Storage & DB | S3 Buckets, RDS Instances, DynamoDB Tables, ElastiCache Clusters, EFS File Systems, EBS Volumes |
| App & Messaging | API Gateway (REST + HTTP), CloudFront, Route 53, ACM Certificates, SNS, SQS, Kinesis Streams, EventBridge Rules |
| Security & Ops | Secrets Manager, KMS Keys, CloudWatch Alarms, CloudWatch Log Groups, CodePipeline, CodeBuild, WAF Web ACLs |
| Other | IAM Roles, Load Balancers (ALB/NLB), Auto Scaling Groups |

---

## Required IAM permissions

The AWS identity you use needs at minimum read access to the services you want to scan. Here's the full policy for scanning everything:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "s3:ListBuckets",
        "s3:GetBucketVersioning",
        "s3:GetBucketEncryption",
        "s3:GetBucketTagging",
        "rds:DescribeDBInstances",
        "iam:ListRoles",
        "iam:ListAttachedRolePolicies",
        "elasticloadbalancing:DescribeLoadBalancers",
        "autoscaling:DescribeAutoScalingGroups",
        "lambda:ListFunctions",
        "ecs:ListClusters",
        "ecs:DescribeClusters",
        "ecs:ListServices",
        "ecs:DescribeServices",
        "ecs:ListTaskDefinitions",
        "ecs:DescribeTaskDefinition",
        "eks:ListClusters",
        "eks:DescribeCluster",
        "ecr:DescribeRepositories",
        "dynamodb:ListTables",
        "dynamodb:DescribeTable",
        "elasticache:DescribeCacheClusters",
        "elasticfilesystem:DescribeFileSystems",
        "apigateway:GET",
        "apigatewayv2:GetApis",
        "cloudfront:ListDistributions",
        "route53:ListHostedZones",
        "acm:ListCertificates",
        "sns:ListTopics",
        "sqs:ListQueues",
        "kinesis:ListStreams",
        "events:ListRules",
        "secretsmanager:ListSecrets",
        "kms:ListKeys",
        "kms:DescribeKey",
        "cloudwatch:DescribeAlarms",
        "logs:DescribeLogGroups",
        "codepipeline:ListPipelines",
        "codebuild:ListProjects",
        "wafv2:ListWebACLs",
        "wafv2:GetWebACL"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Limitations

- **Terraform state** — generated code doesn't import resources into state automatically. Run `terraform import` for each resource before using `terraform apply`.
- **Multi-region** — one run covers one region. Run the container separately for each region you need.
- **Point-in-time snapshot** — the output reflects your infrastructure at the time of the scan. Resources created or changed afterwards won't be included.
- **STS credential lifetime** — when using `--role-arn`, assumed credentials expire after 1 hour by default. The tool prints the expiry time at the start of the scan. For very large accounts, use `--resources` to scan in smaller batches.
