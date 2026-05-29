# cloud-to-iac

Ever inherited an AWS account with zero documentation and had to figure out what's running? That's what this tool is for.

`cloud-to-iac` connects to your live AWS account, discovers what's actually there, and writes it all out as Terraform HCL or CloudFormation YAML — ready to import into state and manage going forward. It covers 41 resource types across networking, compute, storage, databases, messaging, security, and DevOps services.

---

## What it does

- Scans your AWS account using boto3 and produces a full resource inventory
- Generates Terraform or CloudFormation code with real cross-references (so you get `aws_vpc.prod.id` instead of a hardcoded `vpc-0abc1234`)
- Saves an `inventory.json` snapshot so you can re-generate code later without hitting AWS again
- Optionally passes the output through Claude to clean up variable names, fix dependencies, and apply security best practices
- Supports every AWS auth method: access keys, named profiles, IAM instance/task roles, OIDC (GitHub Actions, EKS IRSA), and cross-account role assumption

---

## Quickstart

```bash
# 1. Clone and set up
git clone https://github.com/Mide69/cloud-to-Iac.git
cd cloud-to-Iac

python -m venv venv
source venv/bin/activate          # Mac/Linux
source venv/Scripts/activate      # Windows (Git Bash)
venv\Scripts\activate             # Windows (Command Prompt / PowerShell)

pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
# Edit .env — see Authentication section below

# 3. Run it
python main.py convert --region us-east-1 --format terraform
```

Output lands in `./output/main.tf` and `./output/inventory.json` by default.

---

## Authentication

The tool picks up credentials however boto3 normally would, so most setups work without any extra configuration. Here are the options:

### Option 1 — Access keys in .env

```env
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1
```

### Option 2 — Named AWS CLI profile

```bash
python main.py convert --region us-east-1 --profile your-profile-name
```

This reads from `~/.aws/credentials` as usual.

### Option 3 — IAM role attached to your instance or task

If you're running this on an EC2 instance, ECS task, or Lambda, boto3 picks up the attached role automatically. Nothing to configure.

### Option 4 — OIDC / web identity (GitHub Actions, EKS IRSA, etc.)

Set `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_ARN` in your environment — your CI provider usually does this for you. For GitHub Actions specifically:

```yaml
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: arn:aws:iam::123456789012:role/cloud-to-iac-reader
    aws-region: us-east-1

- run: python main.py convert --region us-east-1 --format terraform
```

No `--role-arn` flag needed. `configure-aws-credentials` handles everything.

### Option 5 — Explicit role assumption (cross-account)

```bash
python main.py convert --region us-east-1 \
  --role-arn arn:aws:iam::123456789012:role/ReadOnlyRole
```

When you use `--role-arn` with Terraform output, the generated provider block automatically includes an `assume_role` stanza so Terraform uses the same role when you run `terraform plan` / `apply`:

```hcl
provider "aws" {
  region = "us-east-1"

  assume_role {
    role_arn     = "arn:aws:iam::123456789012:role/ReadOnlyRole"
    session_name = "terraform"
  }
}
```

---

## Step-by-step usage

### Step 1 — Scan your account first

Before generating anything, run `scan` to see what the tool will find. It's read-only and produces no output files.

```bash
python main.py scan --region us-east-1
```

You'll get a table like this:

```
┌────────────────────────────────┐
│       Discovered Resources     │
├──────────────────────┬─────────┤
│ Resource Type        │ Count   │
├──────────────────────┼─────────┤
│ VPCs                 │ 2       │
│ Subnets              │ 12      │
│ Security Groups      │ 18      │
│ EC2 Instances        │ 7       │
│ Lambda Functions     │ 34      │
│ S3 Buckets           │ 9       │
│ RDS Instances        │ 3       │
│ ECS Clusters         │ 2       │
│ IAM Roles            │ 41      │
│ Total                │ 128     │
└──────────────────────┴─────────┘
```

If something looks wrong — wrong count, missing resources — check your IAM permissions against the list in the [Permissions](#required-iam-permissions) section.

### Step 2 — Generate the IaC

Once you're happy with what the scan sees, run `convert`:

```bash
# Terraform
python main.py convert --region us-east-1 --format terraform --output ./infra

# CloudFormation
python main.py convert --region us-east-1 --format cloudformation --output ./infra
```

This writes three files:
- `infra/main.tf` (or `template.yaml` for CloudFormation)
- `infra/inventory.json` — the raw resource data, useful if you need to re-generate later

### Step 3 — Review the output

Open the generated file before doing anything else. The tool tries to produce clean, ready-to-use code but you'll want to check:

- Names and tags look right
- Cross-references resolved correctly (should say `aws_vpc.prod.id`, not a raw ID)
- Sensitive values like RDS passwords are parameterised (they will be — but double-check)
- Anything the tool couldn't resolve fell back to a hardcoded string (search for `"vpc-` or `"sg-` in the output to find these)

### Step 4 — Import resources into Terraform state

Generated code is just code — Terraform doesn't know about your existing resources until you import them. Do this for each resource:

```bash
cd infra
terraform init
terraform import aws_vpc.prod vpc-0abc1234
terraform import aws_s3_bucket.my_bucket my-bucket-name
# ... repeat for each resource
```

Then run `terraform plan` to confirm there are no unintended changes. If the plan is clean (no additions, changes, or deletions), you're good.

### Step 5 (optional) — Scan only specific resource types

If you only care about certain resources, pass `--resources` to skip everything else:

```bash
python main.py convert --region us-east-1 --resources vpc,subnet,sg,ec2
```

Available filter keys: `vpc`, `subnet`, `igw`, `nat`, `eip`, `rt`, `sg`, `nacl`, `peer`, `endpoint`, `ec2`, `lambda`, `ecs`, `ecstask`, `ecssvc`, `eks`, `ecr`, `s3`, `rds`, `dynamo`, `cache`, `efs`, `ebs`, `apigw`, `httpapi`, `cf`, `r53`, `acm`, `sns`, `sqs`, `kinesis`, `eb`, `secret`, `kms`, `alarm`, `logs`, `pipeline`, `build`, `waf`, `iam`, `alb`, `asg`

### Step 6 (optional) — Re-generate from a saved snapshot

If you've already scanned and saved `inventory.json`, you can re-generate code from it without hitting AWS again:

```bash
python main.py generate ./infra/inventory.json --format terraform --region us-east-1
```

Useful if you want to switch from Terraform to CloudFormation, or try the `--ai` flag after the fact.

### Step 7 (optional) — AI cleanup

Pass `--ai` to send the generated code through Claude for a cleanup pass. It rewrites variable names, fixes obvious dependency ordering issues, and flags anything that looks like a security problem.

```bash
# You need ANTHROPIC_API_KEY set in .env for this
python main.py convert --region us-east-1 --format terraform --ai
```

---

## CloudFormation workflow

```bash
# Validate first
aws cloudformation validate-template \
  --template-body file://infra/template.yaml

# Deploy
aws cloudformation deploy \
  --template-file infra/template.yaml \
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

- **Terraform state**: the generated code doesn't automatically import your resources into state. You still need to run `terraform import` for each resource before `terraform apply` will work safely.
- **Multi-region**: one run covers one region. If you have resources spread across regions, run the tool once per region and combine the outputs.
- **Point-in-time snapshot**: the generated code reflects your infrastructure at the moment you ran the scan. Resources created or changed afterwards won't be included.
- **STS credential lifetime**: if you're using `--role-arn`, the assumed credentials expire after 1 hour by default. The tool prints the exact expiry time when a scan starts. For very large accounts, use `--resources` to scan in smaller targeted batches.

---

## Project structure

```
cloud-to-iac/
├── main.py                  # CLI — three commands: convert, scan, generate
├── requirements.txt
├── .env.example
├── discoverer/
│   └── aws_discoverer.py    # All the boto3 API calls live here
├── generators/
│   ├── terraform.py         # Turns the inventory into .tf files
│   ├── cloudformation.py    # Turns the inventory into CloudFormation YAML
│   └── ai_enhancer.py       # Sends output to Claude for cleanup
└── utils/
    └── helpers.py           # Shared utilities: slugify, tag formatting, etc.
```

---

## License

MIT — see [LICENSE](LICENSE).
