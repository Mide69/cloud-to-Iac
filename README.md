# Cloud-to-IaC

A Python CLI tool that connects to your live AWS account, discovers infrastructure across 11 resource types, and generates production-ready **Terraform HCL** or **CloudFormation YAML** — with optional AI-powered cleanup via the Claude API.

---

## Features

- **Automatic discovery** — scans your live AWS environment using boto3
- **Dual output formats** — Terraform (`.tf`) or CloudFormation (`.yaml`)
- **Smart cross-references** — resource IDs are resolved to logical references (e.g. `aws_vpc.prod_vpc.id`) instead of raw strings
- **AI enhancement** — Claude Opus polishes generated code: adds variables, fixes dependencies, applies security best practices
- **Inventory snapshots** — saves a `inventory.json` you can re-generate from later without re-scanning AWS
- **Selective scanning** — target specific resource types instead of scanning everything

### Supported Resource Types

| Resource | Terraform | CloudFormation |
|---|---|---|
| VPC | `aws_vpc` | `AWS::EC2::VPC` |
| Subnets | `aws_subnet` | `AWS::EC2::Subnet` |
| Internet Gateways | `aws_internet_gateway` | `AWS::EC2::InternetGateway` |
| Route Tables | `aws_route_table` | `AWS::EC2::RouteTable` |
| Security Groups | `aws_security_group` | `AWS::EC2::SecurityGroup` |
| EC2 Instances | `aws_instance` | `AWS::EC2::Instance` |
| S3 Buckets | `aws_s3_bucket` | `AWS::S3::Bucket` |
| RDS Instances | `aws_db_instance` | `AWS::RDS::DBInstance` |
| IAM Roles | `aws_iam_role` | `AWS::IAM::Role` |
| Load Balancers (ALB/NLB) | `aws_lb` | `AWS::ElasticLoadBalancingV2::LoadBalancer` |
| Auto Scaling Groups | `aws_autoscaling_group` | *(scanning only)* |

---

## Prerequisites

- Python 3.9+
- AWS credentials configured (CLI profile, environment variables, or IAM role)
- An AWS account with at least read-only permissions

### Required AWS IAM Permissions

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
        "rds:DescribeDBInstances",
        "iam:ListRoles",
        "iam:ListAttachedRolePolicies",
        "elasticloadbalancing:DescribeLoadBalancers",
        "autoscaling:DescribeAutoScalingGroups"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Installation

```bash
# Clone the repo
git clone https://github.com/Mide69/cloud-to-Iac.git
cd cloud-to-Iac

# Create a virtual environment
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```env
# Option 1: explicit keys
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1

# Option 2: use an AWS CLI named profile (pass --profile to the CLI instead)

# Claude API key — only needed if using the --ai flag
ANTHROPIC_API_KEY=your_anthropic_api_key
```

---

## Usage

### `convert` — Discover and generate in one step

```bash
# Generate Terraform for us-east-1 (default)
python main.py convert --region us-east-1 --format terraform

# Generate CloudFormation
python main.py convert --region eu-west-1 --format cloudformation

# Use a named AWS CLI profile
python main.py convert --region us-east-1 --profile my-profile

# Add AI polish (requires ANTHROPIC_API_KEY)
python main.py convert --region us-east-1 --format terraform --ai

# Preview output in terminal without writing files
python main.py convert --region us-east-1 --dry-run

# Scan only specific resource types
python main.py convert --region us-east-1 --resources vpc,subnet,ec2,sg

# Write to a custom output directory
python main.py convert --region us-east-1 --output ./my-infra
```

### `scan` — Preview discovered resources without generating code

```bash
python main.py scan --region us-east-1
```

Output:

```
┌──────────────────────────────────┐
│       Discovered Resources       │
├─────────────────────┬────────────┤
│ Resource Type       │ Count      │
├─────────────────────┼────────────┤
│ VPCs                │ 2          │
│ Subnets             │ 8          │
│ Internet Gateways   │ 2          │
│ Security Groups     │ 14         │
│ EC2 Instances       │ 6          │
│ S3 Buckets          │ 12         │
│ RDS Instances       │ 3          │
│ IAM Roles           │ 22         │
│ Load Balancers      │ 2          │
│ Total               │ 71         │
└─────────────────────┴────────────┘
```

### `generate` — Re-generate from a saved inventory snapshot

```bash
# Generate Terraform from a previously saved inventory.json
python main.py generate ./output/inventory.json --format terraform --region us-east-1

# Generate CloudFormation with AI enhancement
python main.py generate ./output/inventory.json --format cloudformation --ai
```

---

## Output Files

After running `convert`, the output directory (default: `./output`) contains:

| File | Description |
|---|---|
| `main.tf` | Terraform HCL (when `--format terraform`) |
| `template.yaml` | CloudFormation YAML (when `--format cloudformation`) |
| `inventory.json` | Raw resource inventory — use with `generate` command to re-generate without re-scanning |

---

## Terraform Workflow After Generation

```bash
cd output

# 1. Initialise providers
terraform init

# 2. Review the generated code and fill in any variables
#    (RDS passwords will be prompted automatically)

# 3. Import existing resources into Terraform state
#    Example:
terraform import aws_vpc.prod_vpc vpc-0abc123456

# 4. Verify no unintended changes
terraform plan

# 5. Apply only if you intend to make changes
terraform apply
```

> **Note:** The generated code reflects your infrastructure at the time of scanning. Always run `terraform plan` before `apply` to confirm no destructive changes are planned.

---

## CloudFormation Workflow After Generation

```bash
# Deploy as a new stack
aws cloudformation deploy \
  --template-file output/template.yaml \
  --stack-name my-imported-stack \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides myDbPassword=supersecret

# Validate the template first
aws cloudformation validate-template \
  --template-body file://output/template.yaml
```

---

## Project Structure

```
cloud-to-iac/
├── main.py                          # CLI entry point (Click-based)
├── requirements.txt
├── .env.example                     # Environment variable template
├── discoverer/
│   └── aws_discoverer.py           # Calls AWS APIs via boto3
├── generators/
│   ├── terraform.py                # Produces Terraform HCL
│   ├── cloudformation.py           # Produces CloudFormation YAML
│   └── ai_enhancer.py             # Claude API integration
├── utils/
│   └── helpers.py                  # Slugify, tag formatters, SG rule helpers
└── mappers/                        # Reserved for future provider mappers
```

---

## How It Works

```
AWS Account
    │
    ▼
AWSDiscoverer (boto3)
    │  describe_vpcs / describe_instances / list_buckets / etc.
    ▼
Resource Inventory (dict)
    │
    ├──► TerraformGenerator    → resolves IDs to references → main.tf
    │
    ├──► CloudFormationGenerator → builds CFN resource map → template.yaml
    │
    └──► AIEnhancer (optional) → Claude Opus review → improved output
```

Cross-references are resolved automatically. For example, if a subnet belongs to `vpc-0abc123`, the generator checks whether that VPC was discovered in the same scan. If it was, it emits `aws_vpc.prod_vpc.id`; if not, it falls back to the raw ID string.

---

## Limitations

- **Terraform state**: generated code alone does not manage state. You must run `terraform import` for each resource before using `terraform apply`.
- **Custom resources**: Lambda, ECS, EKS, CloudFront, and other services are not yet supported.
- **Multi-region**: each run targets one region. Run multiple times with different `--region` flags for multi-region setups.
- **Drift**: generated code is a snapshot. Changes made to AWS after the scan will not be reflected.

---

## Roadmap

- [ ] Lambda functions
- [ ] ECS / EKS clusters
- [ ] CloudFront distributions
- [ ] Multi-region output with workspaces
- [ ] Terraform modules (group resources by VPC/environment)
- [ ] Azure and GCP support

---

## License

MIT License — see [LICENSE](LICENSE) for details.
