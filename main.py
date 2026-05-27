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
@click.option("--format", "-f", "output_format", type=click.Choice(["terraform", "cloudformation"]), default="terraform", show_default=True, help="Output IaC format")
@click.option("--output", "-o", default="./output", show_default=True, help="Output directory")
@click.option("--ai", is_flag=True, default=False, help="Enhance output with Claude AI")
@click.option("--dry-run", is_flag=True, default=False, help="Print to stdout without writing files")
@click.option("--resources", "-R", default=None, help="Comma-separated list of resource types to scan (vpc,subnet,ec2,s3,rds,iam,sg,igw,alb,asg)")
def convert(region, profile, output_format, output, ai, dry_run, resources):
    """Discover AWS infrastructure and generate IaC code."""
    console.print(Panel.fit(
        f"[bold green]Cloud → IaC Converter[/bold green]\n"
        f"Region: [cyan]{region}[/cyan]  |  Format: [cyan]{output_format}[/cyan]  |  AI: [cyan]{ai}[/cyan]",
        title="cloud-to-iac"
    ))

    # Discover
    discoverer = AWSDiscoverer(region=region, profile=profile)
    all_resources = discoverer.discover_all()

    # Filter resource types if specified
    if resources:
        allowed = set(resources.split(","))
        type_map = {
            "vpc": "vpcs", "subnet": "subnets", "igw": "internet_gateways",
            "rt": "route_tables", "sg": "security_groups", "ec2": "ec2_instances",
            "s3": "s3_buckets", "rds": "rds_instances", "iam": "iam_roles",
            "alb": "load_balancers", "asg": "auto_scaling_groups",
        }
        all_resources = {type_map[k]: v for k, v in [(k, all_resources.get(type_map.get(k, k), [])) for k in allowed] if k in type_map}

    _print_summary(all_resources)

    # Generate
    if output_format == "terraform":
        generator = TerraformGenerator(resources=all_resources, region=region)
        code = generator.generate()
        ext = "tf"
        filename = "main.tf"
    else:
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
def scan(region, profile):
    """Scan and display a summary of discovered resources without generating code."""
    console.print(f"[bold cyan]Scanning {region}...[/bold cyan]")
    discoverer = AWSDiscoverer(region=region, profile=profile)
    resources = discoverer.discover_all()
    _print_summary(resources)


@cli.command()
@click.argument("inventory_file", type=click.Path(exists=True))
@click.option("--format", "-f", "output_format", type=click.Choice(["terraform", "cloudformation"]), default="terraform")
@click.option("--output", "-o", default="./output")
@click.option("--region", "-r", default="us-east-1")
@click.option("--ai", is_flag=True, default=False)
def generate(inventory_file, output_format, output, region, ai):
    """Generate IaC from a previously saved inventory JSON file."""
    with open(inventory_file) as f:
        all_resources = json.load(f)

    console.print(f"[cyan]Loaded inventory from {inventory_file}[/cyan]")
    _print_summary(all_resources)

    if output_format == "terraform":
        generator = TerraformGenerator(resources=all_resources, region=region)
        code = generator.generate()
        filename = "main.tf"
    else:
        generator = CloudFormationGenerator(resources=all_resources, region=region)
        code = generator.generate()
        filename = "template.yaml"

    if ai:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
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
        "vpcs": "VPCs", "subnets": "Subnets", "internet_gateways": "Internet Gateways",
        "route_tables": "Route Tables", "security_groups": "Security Groups",
        "ec2_instances": "EC2 Instances", "s3_buckets": "S3 Buckets",
        "rds_instances": "RDS Instances", "iam_roles": "IAM Roles",
        "load_balancers": "Load Balancers", "auto_scaling_groups": "Auto Scaling Groups",
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
