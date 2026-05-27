import re
import json


def slugify(value: str) -> str:
    """Convert a string to a valid Terraform resource name."""
    value = re.sub(r"[^a-zA-Z0-9_-]", "_", str(value))
    value = re.sub(r"_+", "_", value)
    return value.strip("_").lower() or "resource"


def tags_to_tf(tags: dict, indent: int = 2) -> str:
    if not tags:
        return "{}"
    pad = " " * indent
    lines = ["{"]
    for k, v in tags.items():
        lines.append(f'{pad}  {json.dumps(k)} = {json.dumps(v)}')
    lines.append(f"{pad}}}")
    return "\n".join(lines)


def tags_to_cfn(tags: dict) -> list:
    return [{"Key": k, "Value": v} for k, v in (tags or {}).items()]


def sg_rule_to_tf(rule: dict, idx: int, direction: str) -> str:
    lines = []
    from_port = rule.get("FromPort", -1)
    to_port = rule.get("ToPort", -1)
    protocol = rule.get("IpProtocol", "-1")
    if protocol == "-1":
        protocol = "-1"
        from_port = 0
        to_port = 0

    for cidr in rule.get("IpRanges", []):
        lines.append(f"""
  {direction} {{
    from_port   = {from_port}
    to_port     = {to_port}
    protocol    = "{protocol}"
    cidr_blocks = ["{cidr['CidrIp']}"]
  }}""")

    for sg_ref in rule.get("UserIdGroupPairs", []):
        lines.append(f"""
  {direction} {{
    from_port       = {from_port}
    to_port         = {to_port}
    protocol        = "{protocol}"
    security_groups = ["{sg_ref['GroupId']}"]
  }}""")

    return "".join(lines)
