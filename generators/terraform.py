import json
from utils.helpers import slugify, tags_to_tf, sg_rule_to_tf


class TerraformGenerator:
    def __init__(self, resources: dict, region: str, role_arn: str = None):
        self.resources = resources
        self.region = region
        self.role_arn = role_arn
        self._id_map = {}

    def generate(self) -> str:
        self._build_id_map()
        sections = [
            self._provider_block(),
            *self._vpcs(), *self._subnets(), *self._igws(),
            *self._nat_gateways(), *self._eips(), *self._route_tables(),
            *self._security_groups(), *self._nacls(),
            *self._vpc_peering(), *self._vpc_endpoints(),
            *self._ec2_instances(), *self._lambda_functions(),
            *self._ecs_clusters(), *self._ecs_task_definitions(), *self._ecs_services(),
            *self._eks_clusters(), *self._ecr_repos(),
            *self._s3_buckets(), *self._rds_instances(),
            *self._dynamodb_tables(), *self._elasticache_clusters(),
            *self._efs_file_systems(), *self._ebs_volumes(),
            *self._rest_apis(), *self._http_apis(),
            *self._cloudfront_distributions(), *self._route53_zones(),
            *self._acm_certificates(), *self._sns_topics(), *self._sqs_queues(),
            *self._kinesis_streams(), *self._eventbridge_rules(),
            *self._secrets(), *self._kms_keys(),
            *self._cloudwatch_alarms(), *self._log_groups(),
            *self._codepipelines(), *self._codebuild_projects(), *self._waf_acls(),
            *self._load_balancers(), *self._iam_roles(), *self._auto_scaling_groups(),
        ]
        return "\n\n".join(filter(None, sections))

    def _build_id_map(self):
        self._id_map.clear()
        for vpc in self.resources.get("vpcs", []):
            name = vpc["tags"].get("Name", vpc["id"])
            self._id_map[vpc["id"]] = f"aws_vpc.{slugify(name)}"
        for s in self.resources.get("subnets", []):
            name = s["tags"].get("Name", s["id"])
            self._id_map[s["id"]] = f"aws_subnet.{slugify(name)}"
        for igw in self.resources.get("internet_gateways", []):
            name = igw["tags"].get("Name", igw["id"])
            self._id_map[igw["id"]] = f"aws_internet_gateway.{slugify(name)}"
        for nat in self.resources.get("nat_gateways", []):
            name = nat["tags"].get("Name", nat["id"])
            self._id_map[nat["id"]] = f"aws_nat_gateway.{slugify(name)}"
        for eip in self.resources.get("elastic_ips", []):
            self._id_map[eip["allocation_id"]] = f"aws_eip.{slugify(eip['allocation_id'])}"
        for rt in self.resources.get("route_tables", []):
            name = rt["tags"].get("Name", rt["id"])
            self._id_map[rt["id"]] = f"aws_route_table.{slugify(name)}"
        for sg in self.resources.get("security_groups", []):
            self._id_map[sg["id"]] = f"aws_security_group.{slugify(sg['name'])}"

    def _ref(self, raw_id: str, attr: str = "id") -> str:
        tf_ref = self._id_map.get(raw_id)
        return f"{tf_ref}.{attr}" if tf_ref else f'"{raw_id}"'

    def _provider_block(self) -> str:
        assume_role_block = ""
        if self.role_arn:
            if any(c in self.role_arn for c in ('"', '\n', '\r', '\\', '$', '{')):
                raise ValueError(f"role_arn contains characters that are invalid in an ARN: {self.role_arn!r}")
            assume_role_block = f'''
  assume_role {{
    role_arn     = "{self.role_arn}"
    session_name = "terraform"
  }}'''
        return f'''terraform {{
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}
}}

provider "aws" {{
  region = "{self.region}"{assume_role_block}
}}'''

    # ── Networking ────────────────────────────────────────────────────────────

    def _vpcs(self) -> list:
        blocks = []
        for vpc in self.resources.get("vpcs", []):
            name = vpc["tags"].get("Name", vpc["id"])
            slug = slugify(name)
            tags = {**vpc["tags"], "Name": vpc["tags"].get("Name", name)}
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
            tags = {**s["tags"], "Name": s["tags"].get("Name", name)}
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
            vpc_ref = self._ref(igw["vpc_id"]) if igw.get("vpc_id") else '""'
            blocks.append(f'''resource "aws_internet_gateway" "{slug}" {{
  vpc_id = {vpc_ref}

  tags = {tags_to_tf({**igw["tags"], "Name": name})}
}}''')
        return blocks

    def _nat_gateways(self) -> list:
        blocks = []
        for nat in self.resources.get("nat_gateways", []):
            name = nat["tags"].get("Name", nat["id"])
            slug = slugify(name)
            subnet_ref = self._ref(nat["subnet_id"])
            connectivity = nat.get("connectivity_type", "public")
            eip_line = ""
            if connectivity == "public" and nat.get("eip_allocation_id"):
                eip_ref = self._ref(nat["eip_allocation_id"], "id")
                eip_line = f"\n  allocation_id = {eip_ref}"
            blocks.append(f'''resource "aws_nat_gateway" "{slug}" {{
  subnet_id         = {subnet_ref}
  connectivity_type = "{connectivity}"{eip_line}

  tags = {tags_to_tf({**nat["tags"], "Name": name})}
}}''')
        return blocks

    def _eips(self) -> list:
        blocks = []
        for eip in self.resources.get("elastic_ips", []):
            slug = slugify(eip["allocation_id"])
            tags = eip.get("tags", {})
            blocks.append(f'''resource "aws_eip" "{slug}" {{
  domain = "{eip.get('domain', 'vpc')}"

  tags = {tags_to_tf(tags)}
}}''')
        return blocks

    def _route_tables(self) -> list:
        blocks = []
        for rt in self.resources.get("route_tables", []):
            name = rt["tags"].get("Name", rt["id"])
            slug = slugify(name)
            vpc_ref = self._ref(rt["vpc_id"])
            route_blocks = ""
            for r in rt["routes"]:
                if not r["cidr"] or r["cidr"] == "local":
                    continue
                gw = r.get("gateway_id") or r.get("nat_gateway_id") or r.get("instance_id") or r.get("vpc_peering_id") or ""
                gw_ref = self._ref(gw) if gw else '""'
                route_blocks += f'\n  route {{\n    cidr_block = "{r["cidr"]}"\n    gateway_id = {gw_ref}\n  }}'
            blocks.append(f'''resource "aws_route_table" "{slug}" {{
  vpc_id = {vpc_ref}
{route_blocks}

  tags = {tags_to_tf({**rt["tags"], "Name": name})}
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
            ingress = "".join(sg_rule_to_tf(r, i, "ingress") for i, r in enumerate(sg.get("ingress", [])))
            egress = "".join(sg_rule_to_tf(r, i, "egress") for i, r in enumerate(sg.get("egress", [])))
            blocks.append(f'''resource "aws_security_group" "{slug}" {{
  name        = "{sg['name']}"
  description = "{sg['description']}"
  vpc_id      = {vpc_ref}
{ingress}
{egress}

  tags = {tags_to_tf({**sg.get("tags", {}), "Name": sg["name"]})}
}}''')
        return blocks

    def _nacls(self) -> list:
        blocks = []
        for acl in self.resources.get("network_acls", []):
            if acl.get("is_default"):
                continue
            name = acl["tags"].get("Name", acl["id"])
            slug = slugify(name)
            vpc_ref = self._ref(acl["vpc_id"])
            subnet_refs = "[" + ", ".join(self._ref(s) for s in acl.get("subnet_ids", [])) + "]"
            entry_blocks = ""
            for e in acl.get("entries", []):
                if e["rule_number"] >= 32767:
                    continue
                from_port = e.get("from_port") or 0
                to_port = e.get("to_port") or 0
                entry_blocks += f'''
  ingress {{
    rule_no    = {e['rule_number']}
    action     = "{e['rule_action']}"
    protocol   = "{e['protocol']}"
    cidr_block = "{e['cidr']}"
    from_port  = {from_port}
    to_port    = {to_port}
  }}''' if not e["egress"] else f'''
  egress {{
    rule_no    = {e['rule_number']}
    action     = "{e['rule_action']}"
    protocol   = "{e['protocol']}"
    cidr_block = "{e['cidr']}"
    from_port  = {from_port}
    to_port    = {to_port}
  }}'''
            blocks.append(f'''resource "aws_network_acl" "{slug}" {{
  vpc_id     = {vpc_ref}
  subnet_ids = {subnet_refs}
{entry_blocks}

  tags = {tags_to_tf({**acl["tags"], "Name": name})}
}}''')
        return blocks

    def _vpc_peering(self) -> list:
        blocks = []
        for p in self.resources.get("vpc_peering", []):
            slug = slugify(p["id"])
            requester_ref = self._ref(p["requester_vpc_id"])
            accepter_ref = self._ref(p["accepter_vpc_id"])
            blocks.append(f'''resource "aws_vpc_peering_connection" "{slug}" {{
  vpc_id      = {requester_ref}
  peer_vpc_id = {accepter_ref}
  auto_accept = true

  tags = {tags_to_tf({**p["tags"], "Name": p["id"]})}
}}''')
        return blocks

    def _vpc_endpoints(self) -> list:
        blocks = []
        for ep in self.resources.get("vpc_endpoints", []):
            slug = slugify(ep["id"])
            vpc_ref = self._ref(ep["vpc_id"])
            ep_type = ep.get("endpoint_type", "Gateway")
            rt_refs = "[" + ", ".join(self._ref(r) for r in ep.get("route_table_ids", [])) + "]"
            subnet_refs = "[" + ", ".join(self._ref(s) for s in ep.get("subnet_ids", [])) + "]"
            extra = f'\n  route_table_ids = {rt_refs}' if ep_type == "Gateway" and ep.get("route_table_ids") else ""
            extra += f'\n  subnet_ids      = {subnet_refs}' if ep_type == "Interface" and ep.get("subnet_ids") else ""
            blocks.append(f'''resource "aws_vpc_endpoint" "{slug}" {{
  vpc_id            = {vpc_ref}
  service_name      = "{ep['service_name']}"
  vpc_endpoint_type = "{ep_type}"{extra}

  tags = {tags_to_tf({**ep["tags"], "Name": ep["id"]})}
}}''')
        return blocks

    # ── Compute & containers ──────────────────────────────────────────────────

    def _ec2_instances(self) -> list:
        blocks = []
        for i in self.resources.get("ec2_instances", []):
            name = i["tags"].get("Name", i["id"])
            slug = slugify(name)
            subnet_ref = self._ref(i["subnet_id"]) if i.get("subnet_id") else '""'
            sg_refs = "[" + ", ".join(self._ref(sg) for sg in i.get("security_groups", [])) + "]"
            key_line = f'\n  key_name               = "{i["key_name"]}"' if i.get("key_name") else ""
            iam_line = f'\n  iam_instance_profile   = "{i["iam_profile"].split("/")[-1]}"' if i.get("iam_profile") else ""
            blocks.append(f'''resource "aws_instance" "{slug}" {{
  ami                    = "{i['ami']}"
  instance_type          = "{i['type']}"
  subnet_id              = {subnet_ref}
  vpc_security_group_ids = {sg_refs}{key_line}{iam_line}
  ebs_optimized          = {str(i.get('ebs_optimized', False)).lower()}
  monitoring             = {str(i.get('monitoring', False)).lower()}

  tags = {tags_to_tf({**i["tags"], "Name": name})}
}}''')
        return blocks

    def _lambda_functions(self) -> list:
        blocks = []
        for fn in self.resources.get("lambda_functions", []):
            slug = slugify(fn["name"])
            env_block = ""
            if fn.get("environment"):
                env_vars = "\n".join(f'      {json.dumps(k)} = "{v}"' for k, v in fn["environment"].items())
                env_block = f'\n  environment {{\n    variables = {{\n{env_vars}\n    }}\n  }}'
            vpc_block = ""
            if fn.get("subnet_ids") and fn.get("security_group_ids"):
                subnets = "[" + ", ".join(f'"{s}"' for s in fn["subnet_ids"]) + "]"
                sgs = "[" + ", ".join(f'"{s}"' for s in fn["security_group_ids"]) + "]"
                vpc_block = f'\n  vpc_config {{\n    subnet_ids         = {subnets}\n    security_group_ids = {sgs}\n  }}'
            layers = "[" + ", ".join(f'"{l}"' for l in fn.get("layers", [])) + "]" if fn.get("layers") else "[]"
            arch = fn.get("architectures", ["x86_64"])[0]
            blocks.append(f'''resource "aws_lambda_function" "{slug}" {{
  function_name = "{fn['name']}"
  description   = "{fn.get('description', '')}"
  role          = "{fn['role']}"
  runtime       = "{fn['runtime']}"
  handler       = "{fn['handler']}"
  memory_size   = {fn.get('memory', 128)}
  timeout       = {fn.get('timeout', 3)}
  architectures = ["{arch}"]
  layers        = {layers}

  filename = "placeholder.zip"
{env_block}{vpc_block}

  tags = {tags_to_tf(fn.get('tags', {}))}
}}''')
        return blocks

    def _ecs_clusters(self) -> list:
        return [
            f'''resource "aws_ecs_cluster" "{slugify(c['name'])}" {{
  name = "{c['name']}"

  tags = {tags_to_tf(c.get('tags', {}))}
}}'''
            for c in self.resources.get("ecs_clusters", [])
        ]

    def _ecs_task_definitions(self) -> list:
        blocks = []
        for td in self.resources.get("ecs_task_definitions", []):
            slug = slugify(td["family"])
            container_defs = json.dumps(td.get("container_definitions", []), indent=2)
            compat = '["' + '", "'.join(td.get("requires_compatibilities", ["EC2"])) + '"]'
            exec_role = f'\n  execution_role_arn       = "{td["execution_role_arn"]}"' if td.get("execution_role_arn") else ""
            task_role = f'\n  task_role_arn            = "{td["task_role_arn"]}"' if td.get("task_role_arn") else ""
            cpu_line = f'\n  cpu                      = "{td["cpu"]}"' if td.get("cpu") else ""
            mem_line = f'\n  memory                   = "{td["memory"]}"' if td.get("memory") else ""
            blocks.append(f'''resource "aws_ecs_task_definition" "{slug}" {{
  family                   = "{td['family']}"
  network_mode             = "{td.get('network_mode', 'bridge')}"
  requires_compatibilities = {compat}{exec_role}{task_role}{cpu_line}{mem_line}

  container_definitions = jsonencode({container_defs})
}}''')
        return blocks

    def _ecs_services(self) -> list:
        blocks = []
        for svc in self.resources.get("ecs_services", []):
            slug = slugify(f"{svc['cluster']}_{svc['name']}")
            assign_pub = svc.get("assign_public_ip", "DISABLED")
            subnets = "[" + ", ".join(f'"{s}"' for s in svc.get("subnets", [])) + "]"
            sgs = "[" + ", ".join(f'"{s}"' for s in svc.get("security_groups", [])) + "]"
            net_block = ""
            if svc.get("subnets"):
                net_block = f'''
  network_configuration {{
    subnets          = {subnets}
    security_groups  = {sgs}
    assign_public_ip = {"true" if assign_pub == "ENABLED" else "false"}
  }}'''
            blocks.append(f'''resource "aws_ecs_service" "{slug}" {{
  name            = "{svc['name']}"
  cluster         = "{svc['cluster']}"
  task_definition = "{svc.get('task_definition', '')}"
  desired_count   = {svc.get('desired_count', 1)}
  launch_type     = "{svc.get('launch_type', 'FARGATE')}"
{net_block}
}}''')
        return blocks

    def _eks_clusters(self) -> list:
        blocks = []
        for c in self.resources.get("eks_clusters", []):
            slug = slugify(c["name"])
            subnets = "[" + ", ".join(self._ref(s) for s in c.get("subnet_ids", [])) + "]"
            sgs = "[" + ", ".join(f'"{s}"' for s in c.get("security_group_ids", [])) + "]"
            blocks.append(f'''resource "aws_eks_cluster" "{slug}" {{
  name     = "{c['name']}"
  role_arn = "{c['role_arn']}"
  version  = "{c.get('version', '')}"

  vpc_config {{
    subnet_ids              = {subnets}
    security_group_ids      = {sgs}
    endpoint_public_access  = {str(c.get('endpoint_public_access', True)).lower()}
    endpoint_private_access = {str(c.get('endpoint_private_access', False)).lower()}
  }}

  tags = {tags_to_tf(c.get('tags', {}))}
}}''')
        return blocks

    def _ecr_repos(self) -> list:
        blocks = []
        for r in self.resources.get("ecr_repositories", []):
            slug = slugify(r["name"])
            blocks.append(f'''resource "aws_ecr_repository" "{slug}" {{
  name                 = "{r['name']}"
  image_tag_mutability = "{r.get('image_tag_mutability', 'MUTABLE')}"

  image_scanning_configuration {{
    scan_on_push = {str(r.get('scan_on_push', False)).lower()}
  }}

  encryption_configuration {{
    encryption_type = "{r.get('encryption_type', 'AES256')}"
  }}
}}''')
        return blocks

    # ── Storage & databases ───────────────────────────────────────────────────

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
  identifier             = "{db['id']}"
  engine                 = "{db['engine']}"
  engine_version         = "{db['engine_version']}"
  instance_class         = "{db['instance_class']}"
  allocated_storage      = {db['allocated_storage']}
  username               = "{db['username']}"
  password               = var.{slug}_password
  multi_az               = {str(db['multi_az']).lower()}
  publicly_accessible    = {str(db['publicly_accessible']).lower()}
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

    def _dynamodb_tables(self) -> list:
        blocks = []
        for t in self.resources.get("dynamodb_tables", []):
            slug = slugify(t["name"])
            billing = t.get("billing_mode", "PROVISIONED")
            capacity_lines = ""
            if billing == "PROVISIONED":
                capacity_lines = f'\n  read_capacity  = {t.get("read_capacity", 5)}\n  write_capacity = {t.get("write_capacity", 5)}'
            attr_blocks = "\n".join(
                f'  attribute {{\n    name = "{k}"\n    type = "{v}"\n  }}'
                for k, v in t.get("attributes", {}).items()
            )
            stream_block = ""
            if t.get("stream_enabled"):
                stream_block = f'\n  stream_enabled   = true\n  stream_view_type = "{t.get("stream_view_type", "NEW_AND_OLD_IMAGES")}"'
            gsi_blocks = ""
            for gsi in t.get("global_secondary_indexes", []):
                range_key_line = f'\n    range_key       = "{gsi["range_key"]}"' if gsi.get("range_key") else ""
                gsi_blocks += f'''
  global_secondary_index {{
    name            = "{gsi['name']}"
    hash_key        = "{gsi['hash_key']}"{range_key_line}
    projection_type = "{gsi.get('projection_type', 'ALL')}"
  }}'''
            range_key_line = f'\n  range_key = "{t["range_key"]}"' if t.get("range_key") else ""
            blocks.append(f'''resource "aws_dynamodb_table" "{slug}" {{
  name         = "{t['name']}"
  billing_mode = "{billing}"{capacity_lines}
  hash_key     = "{t['hash_key']}"{range_key_line}
{attr_blocks}{stream_block}
{gsi_blocks}

  point_in_time_recovery {{
    enabled = {str(t.get("point_in_time_recovery", False)).lower()}
  }}
}}''')
        return blocks

    def _elasticache_clusters(self) -> list:
        blocks = []
        for c in self.resources.get("elasticache_clusters", []):
            slug = slugify(c["id"])
            sg_refs = "[" + ", ".join(f'"{sg}"' for sg in c.get("security_groups", [])) + "]"
            blocks.append(f'''resource "aws_elasticache_cluster" "{slug}" {{
  cluster_id           = "{c['id']}"
  engine               = "{c['engine']}"
  engine_version       = "{c.get('engine_version', '')}"
  node_type            = "{c['node_type']}"
  num_cache_nodes      = {c.get('num_nodes', 1)}
  port                 = {c.get('port', 6379)}
  subnet_group_name    = "{c.get('subnet_group', '')}"
  security_group_ids   = {sg_refs}
  parameter_group_name = "{c.get('parameter_group', 'default.redis7')}"
}}''')
        return blocks

    def _efs_file_systems(self) -> list:
        blocks = []
        for fs in self.resources.get("efs_file_systems", []):
            slug = slugify(fs["id"])
            kms_line = f'\n  kms_key_id       = "{fs["kms_key_id"]}"' if fs.get("kms_key_id") else ""
            blocks.append(f'''resource "aws_efs_file_system" "{slug}" {{
  performance_mode = "{fs.get('performance_mode', 'generalPurpose')}"
  throughput_mode  = "{fs.get('throughput_mode', 'bursting')}"
  encrypted        = {str(fs.get('encrypted', False)).lower()}{kms_line}

  tags = {tags_to_tf({**fs.get("tags", {}), "Name": fs["tags"].get("Name", fs["id"])})}
}}''')
        return blocks

    def _ebs_volumes(self) -> list:
        blocks = []
        for v in self.resources.get("ebs_volumes", []):
            if v.get("attachments"):
                continue
            slug = slugify(v["id"])
            iops_line = f'\n  iops       = {v["iops"]}' if v.get("iops") else ""
            throughput_line = f'\n  throughput = {v["throughput"]}' if v.get("throughput") else ""
            kms_line = f'\n  kms_key_id = "{v["kms_key_id"]}"' if v.get("kms_key_id") else ""
            blocks.append(f'''resource "aws_ebs_volume" "{slug}" {{
  availability_zone = "{v['az']}"
  type              = "{v['type']}"
  size              = {v['size']}
  encrypted         = {str(v.get('encrypted', False)).lower()}{iops_line}{throughput_line}{kms_line}

  tags = {tags_to_tf(v.get('tags', {}))}
}}''')
        return blocks

    # ── App, API & messaging ──────────────────────────────────────────────────

    def _rest_apis(self) -> list:
        blocks = []
        for api in self.resources.get("rest_apis", []):
            slug = slugify(api["name"])
            blocks.append(f'''resource "aws_api_gateway_rest_api" "{slug}" {{
  name        = "{api['name']}"
  description = "{api.get('description', '')}"

  endpoint_configuration {{
    types = ["{api.get('endpoint_type', 'REGIONAL')}"]
  }}

  tags = {tags_to_tf(api.get('tags', {}))}
}}''')
        return blocks

    def _http_apis(self) -> list:
        blocks = []
        for api in self.resources.get("http_apis", []):
            slug = slugify(api["name"])
            cors = api.get("cors_configuration", {})
            cors_block = ""
            if cors:
                origins = "[" + ", ".join(f'"{o}"' for o in cors.get("AllowOrigins", ["*"])) + "]"
                methods = "[" + ", ".join(f'"{m}"' for m in cors.get("AllowMethods", ["*"])) + "]"
                cors_block = f'\n  cors_configuration {{\n    allow_origins = {origins}\n    allow_methods = {methods}\n  }}'
            blocks.append(f'''resource "aws_apigatewayv2_api" "{slug}" {{
  name          = "{api['name']}"
  protocol_type = "{api.get('protocol_type', 'HTTP')}"
  description   = "{api.get('description', '')}"{cors_block}

  tags = {tags_to_tf(api.get('tags', {}))}
}}''')
        return blocks

    def _cloudfront_distributions(self) -> list:
        blocks = []
        for d in self.resources.get("cloudfront_distributions", []):
            slug = slugify(d["id"])
            origins_block = ""
            for o in d.get("origins", []):
                origins_block += f'''
  origin {{
    domain_name = "{o['domain']}"
    origin_id   = "{o['id']}"
  }}'''
            aliases = d.get("aliases", [])
            aliases_block = f'\n  aliases = [{", ".join(chr(34) + a + chr(34) for a in aliases)}]' if aliases else ""
            blocks.append(f'''resource "aws_cloudfront_distribution" "{slug}" {{
  enabled             = {str(d.get('enabled', True)).lower()}
  default_root_object = "{d.get('default_root_object', '')}"
  price_class         = "{d.get('price_class', 'PriceClass_All')}"{aliases_block}
{origins_block}

  default_cache_behavior {{
    target_origin_id       = "{d['origins'][0]['id'] if d.get('origins') else ''}"
    viewer_protocol_policy = "{d.get('viewer_protocol_policy', 'redirect-to-https')}"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]

    forwarded_values {{
      query_string = false
      cookies {{ forward = "none" }}
    }}
  }}

  restrictions {{
    geo_restriction {{
      restriction_type = "none"
    }}
  }}

  viewer_certificate {{
    cloudfront_default_certificate = true
  }}
}}''')
        return blocks

    def _route53_zones(self) -> list:
        blocks = []
        for z in self.resources.get("route53_zones", []):
            slug = slugify(z["name"])
            comment_line = f'\n  comment = "{z["comment"]}"' if z.get("comment") else ""
            blocks.append(f'''resource "aws_route53_zone" "{slug}" {{
  name    = "{z['name']}"{comment_line}
  {"" if not z["private"] else ""}
}}''')
        return blocks

    def _acm_certificates(self) -> list:
        blocks = []
        for cert in self.resources.get("acm_certificates", []):
            slug = slugify(cert["domain"])
            san = cert.get("san", [])
            san_block = ""
            extra_domains = [s for s in san if s != cert["domain"]]
            if extra_domains:
                san_block = "\n  subject_alternative_names = [" + ", ".join(f'"{s}"' for s in extra_domains) + "]"
            blocks.append(f'''resource "aws_acm_certificate" "{slug}" {{
  domain_name       = "{cert['domain']}"
  validation_method = "{cert.get('validation_method', 'DNS')}"{san_block}

  lifecycle {{
    create_before_destroy = true
  }}
}}''')
        return blocks

    def _sns_topics(self) -> list:
        blocks = []
        for t in self.resources.get("sns_topics", []):
            slug = slugify(t["name"])
            kms_line = f'\n  kms_master_key_id = "{t["kms_key_id"]}"' if t.get("kms_key_id") else ""
            fifo_line = f'\n  fifo_topic        = true' if t.get("fifo") else ""
            blocks.append(f'''resource "aws_sns_topic" "{slug}" {{
  name         = "{t['name']}"
  display_name = "{t.get('display_name', '')}"{kms_line}{fifo_line}
}}''')
        return blocks

    def _sqs_queues(self) -> list:
        blocks = []
        for q in self.resources.get("sqs_queues", []):
            slug = slugify(q["name"])
            kms_line = f'\n  kms_master_key_id         = "{q["kms_key_id"]}"' if q.get("kms_key_id") else ""
            fifo_line = f'\n  fifo_queue                = true' if q.get("fifo") else ""
            blocks.append(f'''resource "aws_sqs_queue" "{slug}" {{
  name                       = "{q['name']}"
  visibility_timeout_seconds = {q.get('visibility_timeout', 30)}
  message_retention_seconds  = {q.get('message_retention', 345600)}
  delay_seconds              = {q.get('delay_seconds', 0)}
  max_message_size           = {q.get('max_message_size', 262144)}{kms_line}{fifo_line}
}}''')
        return blocks

    def _kinesis_streams(self) -> list:
        blocks = []
        for s in self.resources.get("kinesis_streams", []):
            slug = slugify(s["name"])
            enc_block = ""
            if s.get("encryption_type") == "KMS" and s.get("key_id"):
                enc_block = f'\n  encryption_type = "KMS"\n  key_id          = "{s["key_id"]}"'
            blocks.append(f'''resource "aws_kinesis_stream" "{slug}" {{
  name             = "{s['name']}"
  shard_count      = {s.get('shard_count', 1)}
  retention_period = {s.get('retention_period', 24)}{enc_block}
}}''')
        return blocks

    def _eventbridge_rules(self) -> list:
        blocks = []
        for r in self.resources.get("eventbridge_rules", []):
            slug = slugify(r["name"])
            schedule_line = f'\n  schedule_expression = "{r["schedule"]}"' if r.get("schedule") else ""
            pattern_line = f'\n  event_pattern = jsonencode({r["event_pattern"]})' if r.get("event_pattern") else ""
            role_line = f'\n  role_arn = "{r["role_arn"]}"' if r.get("role_arn") else ""
            blocks.append(f'''resource "aws_cloudwatch_event_rule" "{slug}" {{
  name        = "{r['name']}"
  description = "{r.get('description', '')}"
  state       = "{r.get('state', 'ENABLED')}"{schedule_line}{pattern_line}{role_line}
}}''')
        return blocks

    # ── Security, monitoring & DevOps ─────────────────────────────────────────

    def _secrets(self) -> list:
        blocks = []
        for s in self.resources.get("secrets", []):
            slug = slugify(s["name"])
            kms_line = f'\n  kms_key_id  = "{s["kms_key_id"]}"' if s.get("kms_key_id") else ""
            rotation_block = ""
            if s.get("rotation_enabled") and s.get("rotation_lambda_arn"):
                rotation_block = f'\n  rotation_lambda_arn = "{s["rotation_lambda_arn"]}"\n  rotation_rules {{ automatically_after_days = 30 }}'
            blocks.append(f'''resource "aws_secretsmanager_secret" "{slug}" {{
  name        = "{s['name']}"
  description = "{s.get('description', '')}"{kms_line}{rotation_block}

  tags = {tags_to_tf(s.get('tags', {}))}
}}''')
        return blocks

    def _kms_keys(self) -> list:
        blocks = []
        for k in self.resources.get("kms_keys", []):
            slug = slugify(k["id"])
            blocks.append(f'''resource "aws_kms_key" "{slug}" {{
  description             = "{k.get('description', '')}"
  deletion_window_in_days = {k.get('deletion_window', 30)}
  enable_key_rotation     = true
  multi_region            = {str(k.get('multi_region', False)).lower()}
}}

resource "aws_kms_alias" "{slug}_alias" {{
  name          = "alias/{slug}"
  target_key_id = aws_kms_key.{slug}.key_id
}}''')
        return blocks

    def _cloudwatch_alarms(self) -> list:
        blocks = []
        for a in self.resources.get("cloudwatch_alarms", []):
            slug = slugify(a["name"])
            dims = ""
            if a.get("dimensions"):
                dim_lines = "\n".join(f'    {json.dumps(k)} = "{v}"' for k, v in a["dimensions"].items())
                dims = f"\n  dimensions = {{\n{dim_lines}\n  }}"
            alarm_actions = "[" + ", ".join(f'"{x}"' for x in a.get("alarm_actions", [])) + "]"
            ok_actions = "[" + ", ".join(f'"{x}"' for x in a.get("ok_actions", [])) + "]"
            blocks.append(f'''resource "aws_cloudwatch_metric_alarm" "{slug}" {{
  alarm_name          = "{a['name']}"
  alarm_description   = "{a.get('description', '')}"
  metric_name         = "{a.get('metric_name', '')}"
  namespace           = "{a.get('namespace', '')}"
  statistic           = "{a.get('statistic', 'Average')}"
  period              = {a.get('period', 300)}
  evaluation_periods  = {a.get('evaluation_periods', 1)}
  threshold           = {a.get('threshold', 0)}
  comparison_operator = "{a.get('comparison_operator', 'GreaterThanThreshold')}"
  alarm_actions       = {alarm_actions}
  ok_actions          = {ok_actions}{dims}
}}''')
        return blocks

    def _log_groups(self) -> list:
        blocks = []
        for g in self.resources.get("cloudwatch_log_groups", []):
            slug = slugify(g["name"])
            retention_line = f'\n  retention_in_days = {g["retention_days"]}' if g.get("retention_days") else ""
            kms_line = f'\n  kms_key_id        = "{g["kms_key_id"]}"' if g.get("kms_key_id") else ""
            blocks.append(f'''resource "aws_cloudwatch_log_group" "{slug}" {{
  name = "{g['name']}"{retention_line}{kms_line}
}}''')
        return blocks

    def _codepipelines(self) -> list:
        blocks = []
        for p in self.resources.get("codepipelines", []):
            slug = slugify(p["name"])
            store = p.get("artifact_store", {})
            blocks.append(f'''resource "aws_codepipeline" "{slug}" {{
  name     = "{p['name']}"
  role_arn = "{p.get('role_arn', '')}"

  artifact_store {{
    location = "{store.get('Location', '')}"
    type     = "{store.get('Type', 'S3')}"
  }}
}}''')
        return blocks

    def _codebuild_projects(self) -> list:
        blocks = []
        for proj in self.resources.get("codebuild_projects", []):
            slug = slugify(proj["name"])
            blocks.append(f'''resource "aws_codebuild_project" "{slug}" {{
  name          = "{proj['name']}"
  description   = "{proj.get('description', '')}"
  service_role  = "{proj.get('service_role', '')}"
  build_timeout = {proj.get('build_timeout', 60)}

  artifacts {{
    type = "{proj.get('artifacts_type', 'NO_ARTIFACTS')}"
  }}

  environment {{
    compute_type = "{proj.get('compute_type', 'BUILD_GENERAL1_SMALL')}"
    image        = "{proj.get('image', 'aws/codebuild/standard:7.0')}"
    type         = "{proj.get('environment_type', 'LINUX_CONTAINER')}"
  }}

  source {{
    type     = "{proj.get('source_type', 'NO_SOURCE')}"
    location = "{proj.get('source_location', '')}"
  }}
}}''')
        return blocks

    def _waf_acls(self) -> list:
        blocks = []
        for acl in self.resources.get("waf_web_acls", []):
            slug = slugify(acl["name"])
            blocks.append(f'''resource "aws_wafv2_web_acl" "{slug}" {{
  name        = "{acl['name']}"
  description = "{acl.get('description', '')}"
  scope       = "{acl.get('scope', 'REGIONAL')}"

  default_action {{
    allow {{}}
  }}

  visibility_config {{
    cloudwatch_metrics_enabled = true
    metric_name                = "{slug}"
    sampled_requests_enabled   = true
  }}
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

    def _iam_roles(self) -> list:
        blocks = []
        for role in self.resources.get("iam_roles", []):
            slug = slugify(role["name"])
            assume_policy = json.dumps(role["assume_role_policy"], indent=2)
            blocks.append(f'''resource "aws_iam_role" "{slug}" {{
  name = "{role['name']}"
  path = "{role['path']}"

  assume_role_policy = <<-JSON
{assume_policy}
JSON
}}''')
            for policy_arn in role.get("attached_policies", []):
                policy_slug = slugify(policy_arn.split("/")[-1])
                blocks.append(f'''resource "aws_iam_role_policy_attachment" "{slug}_{policy_slug}" {{
  role       = aws_iam_role.{slug}.name
  policy_arn = "{policy_arn}"
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
