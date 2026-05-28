#!/usr/bin/env python3
import os
import sys
import json
import click
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from discoverer.aws_discoverer import AWSDiscoverer
from generators.terraform import TerraformGenerator
from generators.cloudformation import CloudFormationGenerator
from generators.ai_enhancer import AIEnhancer

console = Console()


@click.group()
def cli():
    """Cloud-to-IaC: Convert live AWS infrastructure to Terraform or CloudFormation."""
    pass


@cli.command()
@click.option("--region", "-r", default="us-east-1", show_default=True, help="AWS region to scan")
@click.option("--profile", "-p", default=None, help="AWS CLI profile name")
@click.option("--role-arn", default=None, help="IAM role ARN to assume before scanning (supports cross-account and OIDC)")
@click.option("--format", "-f", "output_format", type=click.Choice(["terraform", "cloudformation"]), default="terraform", show_default=True, help="Output IaC format")
@click.option("--output", "-o", default="./output", show_default=True, help="Output directory")
@click.option("--ai", is_flag=True, default=False, help="Enhance output with Claude AI")
@click.option("--dry-run", is_flag=True, default=False, help="Print to stdout without writing files")
@click.option("--resources", "-R", default=None, help="Comma-separated list of resource types to scan (vpc,subnet,ec2,s3,rds,iam,sg,igw,alb,asg)")
def convert(region, profile, role_arn, output_format, output, ai, dry_run, resources):
    """Discover AWS infrastructure and generate IaC code."""
    console.print(Panel.fit(
        f"[bold green]Cloud → IaC Converter[/bold green]\n"
        f"Region: [cyan]{region}[/cyan]  |  Format: [cyan]{output_format}[/cyan]  |  AI: [cyan]{ai}[/cyan]",
        title="cloud-to-iac"
    ))

    # Discover
    try:
        discoverer = AWSDiscoverer(region=region, profile=profile, role_arn=role_arn)
    except RuntimeError as e:
        raise click.ClickException(str(e))
    all_resources = discoverer.discover_all()

    # Filter resource types if specified
    if resources:
        allowed = set(resources.split(","))
        type_map = {
            "vpc": "vpcs", "subnet": "subnets", "igw": "internet_gateways",
            "nat": "nat_gateways", "eip": "elastic_ips",
            "rt": "route_tables", "sg": "security_groups",
            "nacl": "network_acls", "peer": "vpc_peering", "endpoint": "vpc_endpoints",
            "ec2": "ec2_instances", "lambda": "lambda_functions",
            "ecs": "ecs_clusters", "ecstask": "ecs_task_definitions", "ecssvc": "ecs_services",
            "eks": "eks_clusters", "ecr": "ecr_repositories",
            "s3": "s3_buckets", "rds": "rds_instances",
            "dynamo": "dynamodb_tables", "cache": "elasticache_clusters",
            "efs": "efs_file_systems", "ebs": "ebs_volumes",
            "apigw": "rest_apis", "httpapi": "http_apis",
            "cf": "cloudfront_distributions", "r53": "route53_zones",
            "acm": "acm_certificates", "sns": "sns_topics", "sqs": "sqs_queues",
            "kinesis": "kinesis_streams", "eb": "eventbridge_rules",
            "secret": "secrets", "kms": "kms_keys",
            "alarm": "cloudwatch_alarms", "logs": "cloudwatch_log_groups",
            "pipeline": "codepipelines", "build": "codebuild_projects", "waf": "waf_web_acls",
            "iam": "iam_roles", "alb": "load_balancers", "asg": "auto_scaling_groups",
        }
        unknown = allowed - set(type_map)
        if unknown:
            console.print(f"[yellow]Warning: unknown resource type(s) ignored: {', '.join(sorted(unknown))}[/yellow]")
            console.print(f"[yellow]Valid types: {', '.join(sorted(type_map))}[/yellow]")
        all_resources = {type_map[k]: all_resources.get(type_map[k], []) for k in allowed if k in type_map}

    _print_summary(all_resources)

    # Generate
    if output_format == "terraform":
        generator = TerraformGenerator(resources=all_resources, region=region, role_arn=role_arn)
        code = generator.generate()
        ext = "tf"
        filename = "main.tf"
    else:
        if role_arn:
            console.print("[yellow]Warning: --role-arn is only embedded in Terraform provider blocks; it has no effect on CloudFormation output.[/yellow]")
        generator = CloudFormationGenerator(resources=all_resources, region=region)
        code = generator.generate()
        ext = "yaml"
        filename = "template.yaml"

    # AI Enhancement
    if ai:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            console.print("[yellow]Warning: ANTHROPIC_API_KEY not set, skipping AI enhancement[/yellow]")
        else:
            enhancer = AIEnhancer(api_key=api_key)
            code = enhancer.enhance(code, output_format)

    # Output
    if dry_run:
        console.print(f"\n[bold]--- Generated {output_format.upper()} ---[/bold]\n")
        console.print(code)
    else:
        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / filename

        out_file.write_text(code, encoding="utf-8")
        console.print(f"\n[bold green]✓ Written to:[/bold green] {out_file.resolve()}")

        # Also save raw inventory JSON
        inventory_file = out_dir / "inventory.json"
        inventory_file.write_text(json.dumps(all_resources, indent=2, default=str), encoding="utf-8")
        console.print(f"[bold green]✓ Inventory saved:[/bold green] {inventory_file.resolve()}")

        if output_format == "terraform":
            console.print("\n[bold]Next steps:[/bold]")
            console.print("  1. [cyan]cd output && terraform init[/cyan]")
            console.print("  2. Review and adjust variables in main.tf")
            console.print("  3. [cyan]terraform import[/cyan] each resource to bring it under state management")
            console.print("  4. [cyan]terraform plan[/cyan] to verify no unintended changes")
        else:
            console.print("\n[bold]Next steps:[/bold]")
            console.print("  1. Review template.yaml for any hardcoded values")
            console.print("  2. [cyan]aws cloudformation deploy --template-file template.yaml --stack-name my-stack[/cyan]")


@cli.command()
@click.option("--region", "-r", default="us-east-1", show_default=True)
@click.option("--profile", "-p", default=None)
@click.option("--role-arn", default=None, help="IAM role ARN to assume before scanning")
def scan(region, profile, role_arn):
    """Scan and display a summary of discovered resources without generating code."""
    console.print(f"[bold cyan]Scanning {region}...[/bold cyan]")
    try:
        discoverer = AWSDiscoverer(region=region, profile=profile, role_arn=role_arn)
    except RuntimeError as e:
        raise click.ClickException(str(e))
    resources = discoverer.discover_all()
    _print_summary(resources)


@cli.command()
@click.argument("inventory_file", type=click.Path(exists=True))
@click.option("--format", "-f", "output_format", type=click.Choice(["terraform", "cloudformation"]), default="terraform")
@click.option("--output", "-o", default="./output")
@click.option("--region", "-r", default="us-east-1")
@click.option("--role-arn", default=None, help="IAM role ARN to embed in the Terraform provider assume_role block")
@click.option("--ai", is_flag=True, default=False)
def generate(inventory_file, output_format, output, region, role_arn, ai):
    """Generate IaC from a previously saved inventory JSON file."""
    with open(inventory_file) as f:
        all_resources = json.load(f)

    console.print(f"[cyan]Loaded inventory from {inventory_file}[/cyan]")
    _print_summary(all_resources)

    if output_format == "terraform":
        generator = TerraformGenerator(resources=all_resources, region=region, role_arn=role_arn)
        code = generator.generate()
        filename = "main.tf"
    else:
        if role_arn:
            console.print("[yellow]Warning: --role-arn is only embedded in Terraform provider blocks; it has no effect on CloudFormation output.[/yellow]")
        generator = CloudFormationGenerator(resources=all_resources, region=region)
        code = generator.generate()
        filename = "template.yaml"

    if ai:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            console.print("[yellow]Warning: ANTHROPIC_API_KEY not set, skipping AI enhancement[/yellow]")
        else:
            enhancer = AIEnhancer(api_key=api_key)
            code = enhancer.enhance(code, output_format)

    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / filename).write_text(code, encoding="utf-8")
    console.print(f"[bold green]✓ Written to:[/bold green] {(out_dir / filename).resolve()}")


def _print_summary(resources: dict):
    table = Table(title="Discovered Resources", show_header=True)
    table.add_column("Resource Type", style="cyan")
    table.add_column("Count", justify="right", style="green")

    labels = {
        # Networking
        "vpcs": "VPCs", "subnets": "Subnets", "internet_gateways": "Internet Gateways",
        "nat_gateways": "NAT Gateways", "elastic_ips": "Elastic IPs",
        "route_tables": "Route Tables", "security_groups": "Security Groups",
        "network_acls": "Network ACLs", "vpc_peering": "VPC Peering Connections",
        "vpc_endpoints": "VPC Endpoints",
        # Compute & containers
        "ec2_instances": "EC2 Instances", "lambda_functions": "Lambda Functions",
        "ecs_clusters": "ECS Clusters", "ecs_task_definitions": "ECS Task Definitions",
        "ecs_services": "ECS Services", "eks_clusters": "EKS Clusters",
        "ecr_repositories": "ECR Repositories",
        # Storage & databases
        "s3_buckets": "S3 Buckets", "rds_instances": "RDS Instances",
        "dynamodb_tables": "DynamoDB Tables", "elasticache_clusters": "ElastiCache Clusters",
        "efs_file_systems": "EFS File Systems", "ebs_volumes": "EBS Volumes",
        # App, API & messaging
        "rest_apis": "API Gateway REST APIs", "http_apis": "API Gateway HTTP APIs",
        "cloudfront_distributions": "CloudFront Distributions",
        "route53_zones": "Route 53 Hosted Zones", "acm_certificates": "ACM Certificates",
        "sns_topics": "SNS Topics", "sqs_queues": "SQS Queues",
        "kinesis_streams": "Kinesis Streams", "eventbridge_rules": "EventBridge Rules",
        # Security, monitoring & DevOps
        "secrets": "Secrets Manager Secrets", "kms_keys": "KMS Keys",
        "cloudwatch_alarms": "CloudWatch Alarms", "cloudwatch_log_groups": "CloudWatch Log Groups",
        "codepipelines": "CodePipelines", "codebuild_projects": "CodeBuild Projects",
        "waf_web_acls": "WAF Web ACLs",
        # Other
        "iam_roles": "IAM Roles", "load_balancers": "Load Balancers",
        "auto_scaling_groups": "Auto Scaling Groups",
    }

    total = 0
    for key, label in labels.items():
        count = len(resources.get(key, []))
        total += count
        if count > 0:
            table.add_row(label, str(count))

    table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]")
    console.print(table)


if __name__ == "__main__":
    cli()
