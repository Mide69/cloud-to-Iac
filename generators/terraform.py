import json
from utils.helpers import slugify, tags_to_tf, sg_rule_to_tf


class TerraformGenerator:
    def __init__(self, resources: dict, region: str):
        self.resources = resources
        self.region = region
        self._id_map = {}  # raw_id -> tf_resource_name

    def generate(self) -> str:
        self._build_id_map()
        blocks = [self._provider_block()]
        blocks += self._vpcs()
        blocks += self._subnets()
        blocks += self._igws()
        blocks += self._route_tables()
        blocks += self._security_groups()
        blocks += self._ec2_instances()
        blocks += self._s3_buckets()
        blocks += self._rds_instances()
        blocks += self._iam_roles()
        blocks += self._load_balancers()
        blocks += self._auto_scaling_groups()
        return "\n\n".join(filter(None, blocks))

    def _build_id_map(self):
        for vpc in self.resources.get("vpcs", []):
            name = vpc["tags"].get("Name", vpc["id"])
            self._id_map[vpc["id"]] = f"aws_vpc.{slugify(name)}"
        for s in self.resources.get("subnets", []):
            name = s["tags"].get("Name", s["id"])
            self._id_map[s["id"]] = f"aws_subnet.{slugify(name)}"
        for igw in self.resources.get("internet_gateways", []):
            name = igw["tags"].get("Name", igw["id"])
            self._id_map[igw["id"]] = f"aws_internet_gateway.{slugify(name)}"
        for rt in self.resources.get("route_tables", []):
            name = rt["tags"].get("Name", rt["id"])
            self._id_map[rt["id"]] = f"aws_route_table.{slugify(name)}"
        for sg in self.resources.get("security_groups", []):
            self._id_map[sg["id"]] = f"aws_security_group.{slugify(sg['name'])}"

    def _ref(self, raw_id: str, attr: str = "id") -> str:
        tf_ref = self._id_map.get(raw_id)
        if tf_ref:
            return f"{tf_ref}.{attr}"
        return f'"{raw_id}"'

    def _provider_block(self) -> str:
        return f'''terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}
}}

provider "aws" {{
  region = "{self.region}"
}}'''

    def _vpcs(self) -> list:
        blocks = []
        for vpc in self.resources.get("vpcs", []):
            name = vpc["tags"].get("Name", vpc["id"])
            slug = slugify(name)
            tags = dict(vpc["tags"])
            tags.setdefault("Name", name)
            blocks.append(f'''resource "aws_vpc" "{slug}" {{
  cidr_block           = "{vpc['cidr']}"
  enable_dns_support   = {str(vpc['enable_dns_support']).lower()}
  enable_dns_hostnames = {str(vpc['enable_dns_hostnames']).lower()}

  tags = {tags_to_tf(tags)}
}}''')
        return blocks

    def _subnets(self) -> list:
        blocks = []
        for s in self.resources.get("subnets", []):
            name = s["tags"].get("Name", s["id"])
            slug = slugify(name)
            vpc_ref = self._ref(s["vpc_id"])
            tags = dict(s["tags"])
            tags.setdefault("Name", name)
            blocks.append(f'''resource "aws_subnet" "{slug}" {{
  vpc_id                  = {vpc_ref}
  cidr_block              = "{s['cidr']}"
  availability_zone       = "{s['az']}"
  map_public_ip_on_launch = {str(s['map_public_ip']).lower()}

  tags = {tags_to_tf(tags)}
}}''')
        return blocks

    def _igws(self) -> list:
        blocks = []
        for igw in self.resources.get("internet_gateways", []):
            name = igw["tags"].get("Name", igw["id"])
            slug = slugify(name)
            vpc_ref = self._ref(igw["vpc_id"]) if igw["vpc_id"] else '""'
            tags = dict(igw["tags"])
            tags.setdefault("Name", name)
            blocks.append(f'''resource "aws_internet_gateway" "{slug}" {{
  vpc_id = {vpc_ref}

  tags = {tags_to_tf(tags)}
}}''')
        return blocks

    def _route_tables(self) -> list:
        blocks = []
        for rt in self.resources.get("route_tables", []):
            name = rt["tags"].get("Name", rt["id"])
            slug = slugify(name)
            vpc_ref = self._ref(rt["vpc_id"])
            tags = dict(rt["tags"])
            tags.setdefault("Name", name)

            route_blocks = ""
            for r in rt["routes"]:
                if r["cidr"] in ("", "local"):
                    continue
                gw = r.get("gateway_id") or r.get("nat_gateway_id") or r.get("instance_id") or ""
                gw_ref = self._ref(gw) if gw else '""'
                route_blocks += f'''
  route {{
    cidr_block = "{r['cidr']}"
    gateway_id = {gw_ref}
  }}'''

            blocks.append(f'''resource "aws_route_table" "{slug}" {{
  vpc_id = {vpc_ref}
{route_blocks}

  tags = {tags_to_tf(tags)}
}}''')

            for subnet_id in rt["subnet_associations"]:
                subnet_ref = self._ref(subnet_id)
                assoc_slug = slugify(f"{slug}_{subnet_id}")
                blocks.append(f'''resource "aws_route_table_association" "{assoc_slug}" {{
  subnet_id      = {subnet_ref}
  route_table_id = aws_route_table.{slug}.id
}}''')

        return blocks

    def _security_groups(self) -> list:
        blocks = []
        for sg in self.resources.get("security_groups", []):
            if sg["name"] == "default":
                continue
            slug = slugify(sg["name"])
            vpc_ref = self._ref(sg["vpc_id"]) if sg.get("vpc_id") else '""'
            tags = dict(sg.get("tags", {}))
            tags.setdefault("Name", sg["name"])

            ingress_rules = ""
            for idx, rule in enumerate(sg.get("ingress", [])):
                ingress_rules += sg_rule_to_tf(rule, idx, "ingress")

            egress_rules = ""
            for idx, rule in enumerate(sg.get("egress", [])):
                egress_rules += sg_rule_to_tf(rule, idx, "egress")

            blocks.append(f'''resource "aws_security_group" "{slug}" {{
  name        = "{sg['name']}"
  description = "{sg['description']}"
  vpc_id      = {vpc_ref}
{ingress_rules}
{egress_rules}

  tags = {tags_to_tf(tags)}
}}''')
        return blocks

    def _ec2_instances(self) -> list:
        blocks = []
        for i in self.resources.get("ec2_instances", []):
            name = i["tags"].get("Name", i["id"])
            slug = slugify(name)
            subnet_ref = self._ref(i["subnet_id"]) if i.get("subnet_id") else '""'
            sg_refs = "[" + ", ".join(self._ref(sg) for sg in i.get("security_groups", [])) + "]"
            tags = dict(i["tags"])
            tags.setdefault("Name", name)

            key_line = f'\n  key_name      = "{i["key_name"]}"' if i.get("key_name") else ""
            iam_line = f'\n  iam_instance_profile = "{i["iam_profile"].split("/")[-1]}"' if i.get("iam_profile") else ""
            monitoring_line = f"\n  monitoring    = {str(i.get('monitoring', False)).lower()}"

            blocks.append(f'''resource "aws_instance" "{slug}" {{
  ami           = "{i['ami']}"
  instance_type = "{i['type']}"
  subnet_id     = {subnet_ref}
  vpc_security_group_ids = {sg_refs}{key_line}{iam_line}{monitoring_line}
  ebs_optimized = {str(i.get('ebs_optimized', False)).lower()}

  tags = {tags_to_tf(tags)}
}}''')
        return blocks

    def _s3_buckets(self) -> list:
        blocks = []
        for b in self.resources.get("s3_buckets", []):
            slug = slugify(b["name"])
            blocks.append(f'''resource "aws_s3_bucket" "{slug}" {{
  bucket = "{b['name']}"
}}''')
            if b.get("versioning"):
                blocks.append(f'''resource "aws_s3_bucket_versioning" "{slug}_versioning" {{
  bucket = aws_s3_bucket.{slug}.id
  versioning_configuration {{
    status = "Enabled"
  }}
}}''')
            if b.get("encryption"):
                blocks.append(f'''resource "aws_s3_bucket_server_side_encryption_configuration" "{slug}_sse" {{
  bucket = aws_s3_bucket.{slug}.id
  rule {{
    apply_server_side_encryption_by_default {{
      sse_algorithm = "{b['encryption']}"
    }}
  }}
}}''')
        return blocks

    def _rds_instances(self) -> list:
        blocks = []
        for db in self.resources.get("rds_instances", []):
            slug = slugify(db["id"])
            sg_refs = "[" + ", ".join(f'"{sg}"' for sg in db.get("security_groups", [])) + "]"
            db_name_line = f'\n  db_name  = "{db["db_name"]}"' if db.get("db_name") else ""
            blocks.append(f'''resource "aws_db_instance" "{slug}" {{
  identifier        = "{db['id']}"
  engine            = "{db['engine']}"
  engine_version    = "{db['engine_version']}"
  instance_class    = "{db['instance_class']}"
  allocated_storage = {db['allocated_storage']}
  username          = "{db['username']}"
  password          = var.{slug}_password
  multi_az          = {str(db['multi_az']).lower()}
  publicly_accessible = {str(db['publicly_accessible']).lower()}
  db_subnet_group_name   = "{db.get('subnet_group', '')}"
  vpc_security_group_ids = {sg_refs}{db_name_line}

  skip_final_snapshot = true
}}

variable "{slug}_password" {{
  description = "Master password for RDS instance {db['id']}"
  type        = string
  sensitive   = true
}}''')
        return blocks

    def _iam_roles(self) -> list:
        blocks = []
        for role in self.resources.get("iam_roles", []):
            slug = slugify(role["name"])
            assume_policy = json.dumps(role["assume_role_policy"], indent=2)
            blocks.append(f'''resource "aws_iam_role" "{slug}" {{
  name = "{role['name']}"
  path = "{role['path']}"

  assume_role_policy = jsonencode({assume_policy})
}}''')
            for policy_arn in role.get("attached_policies", []):
                policy_slug = slugify(policy_arn.split("/")[-1])
                blocks.append(f'''resource "aws_iam_role_policy_attachment" "{slug}_{policy_slug}" {{
  role       = aws_iam_role.{slug}.name
  policy_arn = "{policy_arn}"
}}''')
        return blocks

    def _load_balancers(self) -> list:
        blocks = []
        for lb in self.resources.get("load_balancers", []):
            slug = slugify(lb["name"])
            subnet_refs = "[" + ", ".join(f'"{s}"' for s in lb.get("subnets", [])) + "]"
            sg_refs = "[" + ", ".join(f'"{sg}"' for sg in lb.get("security_groups", [])) + "]"
            internal = "true" if lb.get("scheme") == "internal" else "false"
            blocks.append(f'''resource "aws_lb" "{slug}" {{
  name               = "{lb['name']}"
  internal           = {internal}
  load_balancer_type = "{lb['type']}"
  security_groups    = {sg_refs}
  subnets            = {subnet_refs}
}}''')
        return blocks

    def _auto_scaling_groups(self) -> list:
        blocks = []
        for asg in self.resources.get("auto_scaling_groups", []):
            slug = slugify(asg["name"])
            subnet_refs = "[" + ", ".join(f'"{s}"' for s in asg.get("subnets", []) if s) + "]"
            blocks.append(f'''resource "aws_autoscaling_group" "{slug}" {{
  name                = "{asg['name']}"
  min_size            = {asg['min_size']}
  max_size            = {asg['max_size']}
  desired_capacity    = {asg['desired']}
  vpc_zone_identifier = {subnet_refs}
}}''')
        return blocks
