import anthropic
from rich.console import Console

console = Console()

SYSTEM_PROMPT = """You are an expert Infrastructure-as-Code engineer specializing in Terraform and CloudFormation.
Your job is to review generated IaC code and improve it by:
1. Adding meaningful variable declarations for hardcoded values
2. Fixing any syntax issues
3. Adding proper resource dependencies (depends_on where needed)
4. Improving naming consistency
5. Adding data sources where appropriate instead of hardcoded IDs
6. Ensuring security best practices (no hardcoded secrets, proper IAM least-privilege patterns)
7. Grouping related resources logically with blank lines

Return ONLY the improved code with no markdown fences or explanation."""


class AIEnhancer:
    def __init__(self, api_key: str = None):
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def enhance(self, code: str, output_format: str) -> str:
        console.print("[bold cyan]Running AI enhancement via Claude...[/bold cyan]")
        format_label = "Terraform HCL" if output_format == "terraform" else "CloudFormation YAML"

        message = self.client.messages.create(
            model="claude-opus-4-7",
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Please improve this {format_label} code generated from live AWS infrastructure:\n\n{code}",
                }
            ],
        )

        enhanced = message.content[0].text
        console.print("[green]✓ AI enhancement complete[/green]")
        return enhanced
