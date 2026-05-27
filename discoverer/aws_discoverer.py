import json
import boto3
from botocore.exceptions import ClientError
from rich.console import Console

console = Console()


class AWSDiscoverer:
    def __init__(self, region: str, profile: str = None):
        self.region = region
        session = boto3.Session(profile_name=profile, region_name=region) if profile else boto3.Session(region_name=region)
        # Core
        self.ec2            = session.client("ec2")
        self.s3             = session.client("s3")
        self.rds            = session.client("rds")
        self.iam            = session.client("iam")
        self.elbv2          = session.client("elbv2")
        self.autoscaling    = session.client("autoscaling")
        # Compute & containers
        self.lambda_client  = session.client("lambda")
        self.ecs            = session.client("ecs")
        self.eks            = session.client("eks")
        self.ecr            = session.client("ecr")
        # Storage & databases
        self.dynamodb       = session.client("dynamodb")
        self.elasticache    = session.client("elasticache")
        self.efs_client     = session.client("efs")
        # App, API & messaging
        self.apigateway     = session.client("apigateway")
        self.apigatewayv2   = session.client("apigatewayv2")
        self.cloudfront     = session.client("cloudfront")
        self.route53        = session.client("route53")
        self.acm            = session.client("acm")
        self.sns            = session.client("sns")
        self.sqs            = session.client("sqs")
        self.kinesis        = session.client("kinesis")
        self.events         = session.client("events")
        # Security, monitoring & DevOps
        self.secretsmanager = session.client("secretsmanager")
        self.kms            = session.client("kms")
        self.cloudwatch     = session.client("cloudwatch")
        self.logs           = session.client("logs")
        self.codepipeline   = session.client("codepipeline")
        self.codebuild      = session.client("codebuild")
        self.wafv2          = session.client("wafv2")

    def discover_all(self) -> dict:
        console.print("[bold cyan]Discovering AWS infrastructure...[/bold cyan]")
        resources = {}
        steps = [
            # Networking
            ("vpcs",                    self.discover_vpcs),
            ("subnets",                 self.discover_subnets),
            ("internet_gateways",       self.discover_igws),
            ("nat_gateways",            self.discover_nat_gateways),
            ("elastic_ips",             self.discover_eips),
            ("route_tables",            self.discover_route_tables),
            ("security_groups",         self.discover_security_groups),
            ("network_acls",            self.discover_nacls),
            ("vpc_peering",             self.discover_vpc_peering),
            ("vpc_endpoints",           self.discover_vpc_endpoints),
            # Compute & containers
            ("ec2_instances",           self.discover_ec2),
            ("lambda_functions",        self.discover_lambda),
            ("ecs_clusters",            self.discover_ecs_clusters),
            ("ecs_services",            self.discover_ecs_services),
            ("ecs_task_definitions",    self.discover_ecs_task_defs),
            ("eks_clusters",            self.discover_eks),
            ("ecr_repositories",        self.discover_ecr),
            # Storage & databases
            ("s3_buckets",              self.discover_s3),
            ("rds_instances",           self.discover_rds),
            ("dynamodb_tables",         self.discover_dynamodb),
            ("elasticache_clusters",    self.discover_elasticache),
            ("efs_file_systems",        self.discover_efs),
            ("ebs_volumes",             self.discover_ebs),
            # App, API & messaging
            ("rest_apis",               self.discover_rest_apis),
            ("http_apis",               self.discover_http_apis),
            ("cloudfront_distributions", self.discover_cloudfront),
            ("route53_zones",           self.discover_route53),
            ("acm_certificates",        self.discover_acm),
            ("sns_topics",              self.discover_sns),
            ("sqs_queues",              self.discover_sqs),
            ("kinesis_streams",         self.discover_kinesis),
            ("eventbridge_rules",       self.discover_eventbridge),
            # Security, monitoring & DevOps
            ("secrets",                 self.discover_secrets),
            ("kms_keys",               self.discover_kms),
            ("cloudwatch_alarms",       self.discover_cloudwatch_alarms),
            ("cloudwatch_log_groups",   self.discover_log_groups),
            ("codepipelines",           self.discover_codepipelines),
            ("codebuild_projects",      self.discover_codebuild),
            ("waf_web_acls",           self.discover_waf),
            # Auto scaling
            ("load_balancers",          self.discover_albs),
            ("iam_roles",               self.discover_iam_roles),
            ("auto_scaling_groups",     self.discover_asg),
        ]
        for name, fn in steps:
            try:
                console.print(f"  [yellow]→[/yellow] Scanning {name}...")
                resources[name] = fn()
                if resources[name]:
                    console.print(f"  [green]✓[/green] Found {len(resources[name])} {name}")
                else:
                    console.print(f"  [dim]  0 {name}[/dim]")
            except ClientError as e:
                console.print(f"  [red]✗[/red] {name}: {e.response['Error']['Message']}")
                resources[name] = []
            except Exception as e:
                console.print(f"  [red]✗[/red] {name}: {str(e)[:80]}")
                resources[name] = []
        return resources

    # ── Networking ────────────────────────────────────────────────────────────

    def discover_vpcs(self) -> list:
        vpcs = []
        for v in self.ec2.describe_vpcs()["Vpcs"]:
            vpcs.append({
                "id": v["VpcId"],
                "cidr": v["CidrBlock"],
                "is_default": v.get("IsDefault", False),
                "tags": self._tags(v),
                "enable_dns_support": self._vpc_attr(v["VpcId"], "enableDnsSupport"),
                "enable_dns_hostnames": self._vpc_attr(v["VpcId"], "enableDnsHostnames"),
            })
        return vpcs

    def discover_subnets(self) -> list:
        return [
            {
                "id": s["SubnetId"], "vpc_id": s["VpcId"],
                "cidr": s["CidrBlock"], "az": s["AvailabilityZone"],
                "map_public_ip": s.get("MapPublicIpOnLaunch", False),
                "tags": self._tags(s),
            }
            for s in self.ec2.describe_subnets()["Subnets"]
        ]

    def discover_igws(self) -> list:
        igws = []
        for igw in self.ec2.describe_internet_gateways()["InternetGateways"]:
            attachments = igw.get("Attachments", [])
            igws.append({
                "id": igw["InternetGatewayId"],
                "vpc_id": attachments[0]["VpcId"] if attachments else None,
                "tags": self._tags(igw),
            })
        return igws

    def discover_nat_gateways(self) -> list:
        nats = []
        resp = self.ec2.describe_nat_gateways(Filters=[{"Name": "state", "Values": ["available"]}])
        for n in resp.get("NatGateways", []):
            addrs = n.get("NatGatewayAddresses", [{}])
            nats.append({
                "id": n["NatGatewayId"],
                "subnet_id": n["SubnetId"],
                "vpc_id": n["VpcId"],
                "connectivity_type": n.get("ConnectivityType", "public"),
                "eip_allocation_id": addrs[0].get("AllocationId") if addrs else None,
                "tags": self._tags(n),
            })
        return nats

    def discover_eips(self) -> list:
        eips = []
        for addr in self.ec2.describe_addresses()["Addresses"]:
            eips.append({
                "allocation_id": addr.get("AllocationId", ""),
                "public_ip": addr.get("PublicIp", ""),
                "domain": addr.get("Domain", "vpc"),
                "instance_id": addr.get("InstanceId"),
                "network_interface_id": addr.get("NetworkInterfaceId"),
                "tags": self._tags(addr),
            })
        return eips

    def discover_route_tables(self) -> list:
        rts = []
        for rt in self.ec2.describe_route_tables()["RouteTables"]:
            routes = [
                {
                    "cidr": r.get("DestinationCidrBlock", ""),
                    "gateway_id": r.get("GatewayId"),
                    "nat_gateway_id": r.get("NatGatewayId"),
                    "instance_id": r.get("InstanceId"),
                    "vpc_peering_id": r.get("VpcPeeringConnectionId"),
                }
                for r in rt.get("Routes", [])
            ]
            rts.append({
                "id": rt["RouteTableId"], "vpc_id": rt["VpcId"],
                "routes": routes,
                "subnet_associations": [a["SubnetId"] for a in rt.get("Associations", []) if "SubnetId" in a],
                "tags": self._tags(rt),
            })
        return rts

    def discover_security_groups(self) -> list:
        return [
            {
                "id": sg["GroupId"], "name": sg["GroupName"],
                "description": sg["Description"], "vpc_id": sg.get("VpcId"),
                "ingress": sg.get("IpPermissions", []),
                "egress": sg.get("IpPermissionsEgress", []),
                "tags": self._tags(sg),
            }
            for sg in self.ec2.describe_security_groups()["SecurityGroups"]
        ]

    def discover_nacls(self) -> list:
        nacls = []
        for acl in self.ec2.describe_network_acls()["NetworkAcls"]:
            entries = [
                {
                    "rule_number": e["RuleNumber"], "protocol": e["Protocol"],
                    "rule_action": e["RuleAction"], "egress": e["Egress"],
                    "cidr": e.get("CidrBlock", ""), "from_port": e.get("PortRange", {}).get("From"),
                    "to_port": e.get("PortRange", {}).get("To"),
                }
                for e in acl.get("Entries", [])
            ]
            nacls.append({
                "id": acl["NetworkAclId"], "vpc_id": acl["VpcId"],
                "is_default": acl.get("IsDefault", False),
                "entries": entries,
                "subnet_ids": [a["SubnetId"] for a in acl.get("Associations", [])],
                "tags": self._tags(acl),
            })
        return nacls

    def discover_vpc_peering(self) -> list:
        peers = []
        resp = self.ec2.describe_vpc_peering_connections(
            Filters=[{"Name": "status-code", "Values": ["active"]}]
        )
        for p in resp.get("VpcPeeringConnections", []):
            peers.append({
                "id": p["VpcPeeringConnectionId"],
                "requester_vpc_id": p["RequesterVpcInfo"]["VpcId"],
                "accepter_vpc_id": p["AccepterVpcInfo"]["VpcId"],
                "requester_cidr": p["RequesterVpcInfo"].get("CidrBlock", ""),
                "accepter_cidr": p["AccepterVpcInfo"].get("CidrBlock", ""),
                "tags": self._tags(p),
            })
        return peers

    def discover_vpc_endpoints(self) -> list:
        endpoints = []
        resp = self.ec2.describe_vpc_endpoints()
        for ep in resp.get("VpcEndpoints", []):
            if ep.get("State") != "available":
                continue
            endpoints.append({
                "id": ep["VpcEndpointId"],
                "vpc_id": ep["VpcId"],
                "service_name": ep["ServiceName"],
                "endpoint_type": ep.get("VpcEndpointType", "Gateway"),
                "route_table_ids": ep.get("RouteTableIds", []),
                "subnet_ids": ep.get("SubnetIds", []),
                "tags": self._tags(ep),
            })
        return endpoints

    # ── Compute & containers ──────────────────────────────────────────────────

    def discover_ec2(self) -> list:
        instances = []
        for reservation in self.ec2.describe_instances()["Reservations"]:
            for i in reservation["Instances"]:
                if i["State"]["Name"] == "terminated":
                    continue
                instances.append({
                    "id": i["InstanceId"], "type": i["InstanceType"],
                    "ami": i["ImageId"], "subnet_id": i.get("SubnetId"),
                    "vpc_id": i.get("VpcId"), "key_name": i.get("KeyName"),
                    "iam_profile": i.get("IamInstanceProfile", {}).get("Arn", ""),
                    "security_groups": [sg["GroupId"] for sg in i.get("SecurityGroups", [])],
                    "public_ip": i.get("PublicIpAddress"),
                    "private_ip": i.get("PrivateIpAddress"),
                    "ebs_optimized": i.get("EbsOptimized", False),
                    "monitoring": i.get("Monitoring", {}).get("State") == "enabled",
                    "tags": self._tags(i),
                })
        return instances

    def discover_lambda(self) -> list:
        functions = []
        paginator = self.lambda_client.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page["Functions"]:
                vpc_config = fn.get("VpcConfig", {})
                env_vars = fn.get("Environment", {}).get("Variables", {})
                functions.append({
                    "name": fn["FunctionName"],
                    "arn": fn["FunctionArn"],
                    "runtime": fn.get("Runtime", ""),
                    "handler": fn.get("Handler", ""),
                    "role": fn.get("Role", ""),
                    "memory": fn.get("MemorySize", 128),
                    "timeout": fn.get("Timeout", 3),
                    "description": fn.get("Description", ""),
                    "subnet_ids": vpc_config.get("SubnetIds", []),
                    "security_group_ids": vpc_config.get("SecurityGroupIds", []),
                    "environment": env_vars,
                    "layers": [l["Arn"] for l in fn.get("Layers", [])],
                    "architectures": fn.get("Architectures", ["x86_64"]),
                    "tags": fn.get("Tags", {}),
                })
        return functions

    def discover_ecs_clusters(self) -> list:
        clusters = []
        arns = self.ecs.list_clusters().get("clusterArns", [])
        if not arns:
            return []
        for cluster in self.ecs.describe_clusters(clusters=arns, include=["TAGS"])["clusters"]:
            clusters.append({
                "name": cluster["clusterName"],
                "arn": cluster["clusterArn"],
                "status": cluster.get("status"),
                "tags": {t["key"]: t["value"] for t in cluster.get("tags", [])},
            })
        return clusters

    def discover_ecs_services(self) -> list:
        services = []
        cluster_arns = self.ecs.list_clusters().get("clusterArns", [])
        for cluster_arn in cluster_arns:
            svc_arns = self.ecs.list_services(cluster=cluster_arn).get("serviceArns", [])
            if not svc_arns:
                continue
            for svc in self.ecs.describe_services(cluster=cluster_arn, services=svc_arns)["services"]:
                net_config = svc.get("networkConfiguration", {}).get("awsvpcConfiguration", {})
                services.append({
                    "name": svc["serviceName"],
                    "cluster": cluster_arn.split("/")[-1],
                    "task_definition": svc.get("taskDefinition", ""),
                    "desired_count": svc.get("desiredCount", 1),
                    "launch_type": svc.get("launchType", "FARGATE"),
                    "subnets": net_config.get("subnets", []),
                    "security_groups": net_config.get("securityGroups", []),
                    "assign_public_ip": net_config.get("assignPublicIp", "DISABLED"),
                    "load_balancers": svc.get("loadBalancers", []),
                })
        return services

    def discover_ecs_task_defs(self) -> list:
        task_defs = []
        arns = self.ecs.list_task_definitions(status="ACTIVE").get("taskDefinitionArns", [])
        seen_families = set()
        for arn in reversed(arns):
            family = arn.split("/")[-1].rsplit(":", 1)[0]
            if family in seen_families:
                continue
            seen_families.add(family)
            td = self.ecs.describe_task_definition(taskDefinition=arn)["taskDefinition"]
            task_defs.append({
                "family": td["family"],
                "revision": td["revision"],
                "network_mode": td.get("networkMode", "bridge"),
                "requires_compatibilities": td.get("requiresCompatibilities", []),
                "cpu": td.get("cpu", ""),
                "memory": td.get("memory", ""),
                "execution_role_arn": td.get("executionRoleArn", ""),
                "task_role_arn": td.get("taskRoleArn", ""),
                "container_definitions": td.get("containerDefinitions", []),
            })
        return task_defs

    def discover_eks(self) -> list:
        clusters = []
        names = self.eks.list_clusters().get("clusters", [])
        for name in names:
            c = self.eks.describe_cluster(name=name)["cluster"]
            resources_vpc = c.get("resourcesVpcConfig", {})
            clusters.append({
                "name": c["name"],
                "version": c.get("version", ""),
                "role_arn": c.get("roleArn", ""),
                "subnet_ids": resources_vpc.get("subnetIds", []),
                "security_group_ids": resources_vpc.get("securityGroupIds", []),
                "endpoint_public_access": resources_vpc.get("endpointPublicAccess", True),
                "endpoint_private_access": resources_vpc.get("endpointPrivateAccess", False),
                "tags": c.get("tags", {}),
            })
        return clusters

    def discover_ecr(self) -> list:
        repos = []
        paginator = self.ecr.get_paginator("describe_repositories")
        for page in paginator.paginate():
            for r in page["repositories"]:
                scan_config = r.get("imageScanningConfiguration", {})
                repos.append({
                    "name": r["repositoryName"],
                    "arn": r["repositoryArn"],
                    "uri": r["repositoryUri"],
                    "image_tag_mutability": r.get("imageTagMutability", "MUTABLE"),
                    "scan_on_push": scan_config.get("scanOnPush", False),
                    "encryption_type": r.get("encryptionConfiguration", {}).get("encryptionType", "AES256"),
                })
        return repos

    # ── Storage & databases ───────────────────────────────────────────────────

    def discover_s3(self) -> list:
        buckets = []
        for b in self.s3.list_buckets().get("Buckets", []):
            name = b["Name"]
            bucket = {"name": name, "versioning": False, "encryption": None}
            try:
                v = self.s3.get_bucket_versioning(Bucket=name)
                bucket["versioning"] = v.get("Status") == "Enabled"
            except ClientError:
                pass
            try:
                enc = self.s3.get_bucket_encryption(Bucket=name)
                rules = enc["ServerSideEncryptionConfiguration"]["Rules"]
                bucket["encryption"] = rules[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
            except ClientError:
                pass
            buckets.append(bucket)
        return buckets

    def discover_rds(self) -> list:
        instances = []
        for db in self.rds.describe_db_instances()["DBInstances"]:
            instances.append({
                "id": db["DBInstanceIdentifier"],
                "engine": db["Engine"], "engine_version": db["EngineVersion"],
                "instance_class": db["DBInstanceClass"],
                "allocated_storage": db["AllocatedStorage"],
                "multi_az": db.get("MultiAZ", False),
                "publicly_accessible": db.get("PubliclyAccessible", False),
                "db_name": db.get("DBName", ""),
                "username": db.get("MasterUsername", ""),
                "subnet_group": db.get("DBSubnetGroup", {}).get("DBSubnetGroupName", ""),
                "security_groups": [sg["VpcSecurityGroupId"] for sg in db.get("VpcSecurityGroups", [])],
            })
        return instances

    def discover_dynamodb(self) -> list:
        tables = []
        paginator = self.dynamodb.get_paginator("list_tables")
        for page in paginator.paginate():
            for table_name in page["TableNames"]:
                t = self.dynamodb.describe_table(TableName=table_name)["Table"]
                billing = t.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
                throughput = t.get("ProvisionedThroughput", {})
                gsis = [
                    {
                        "name": g["IndexName"],
                        "hash_key": g["KeySchema"][0]["AttributeName"],
                        "range_key": g["KeySchema"][1]["AttributeName"] if len(g["KeySchema"]) > 1 else None,
                        "read_capacity": g.get("ProvisionedThroughput", {}).get("ReadCapacityUnits", 0),
                        "write_capacity": g.get("ProvisionedThroughput", {}).get("WriteCapacityUnits", 0),
                        "projection_type": g.get("Projection", {}).get("ProjectionType", "ALL"),
                    }
                    for g in t.get("GlobalSecondaryIndexes", [])
                ]
                tables.append({
                    "name": t["TableName"],
                    "hash_key": next((k["AttributeName"] for k in t["KeySchema"] if k["KeyType"] == "HASH"), ""),
                    "range_key": next((k["AttributeName"] for k in t["KeySchema"] if k["KeyType"] == "RANGE"), None),
                    "attributes": {a["AttributeName"]: a["AttributeType"] for a in t.get("AttributeDefinitions", [])},
                    "billing_mode": billing,
                    "read_capacity": throughput.get("ReadCapacityUnits", 0),
                    "write_capacity": throughput.get("WriteCapacityUnits", 0),
                    "stream_enabled": t.get("StreamSpecification", {}).get("StreamEnabled", False),
                    "stream_view_type": t.get("StreamSpecification", {}).get("StreamViewType", ""),
                    "point_in_time_recovery": False,
                    "global_secondary_indexes": gsis,
                    "tags": {},
                })
        return tables

    def discover_elasticache(self) -> list:
        clusters = []
        paginator = self.elasticache.get_paginator("describe_cache_clusters")
        for page in paginator.paginate(ShowCacheNodeInfo=True):
            for c in page["CacheClusters"]:
                clusters.append({
                    "id": c["CacheClusterId"],
                    "engine": c["Engine"],
                    "engine_version": c.get("EngineVersion", ""),
                    "node_type": c["CacheNodeType"],
                    "num_nodes": c.get("NumCacheNodes", 1),
                    "subnet_group": c.get("CacheSubnetGroupName", ""),
                    "security_groups": [sg["SecurityGroupId"] for sg in c.get("SecurityGroups", [])],
                    "parameter_group": c.get("CacheParameterGroup", {}).get("CacheParameterGroupName", ""),
                    "port": c.get("ConfigurationEndpoint", {}).get("Port") or (6379 if c["Engine"] == "redis" else 11211),
                    "az": c.get("PreferredAvailabilityZone", ""),
                })
        return clusters

    def discover_efs(self) -> list:
        file_systems = []
        resp = self.efs_client.describe_file_systems()
        for fs in resp.get("FileSystems", []):
            file_systems.append({
                "id": fs["FileSystemId"],
                "creation_token": fs.get("CreationToken", ""),
                "performance_mode": fs.get("PerformanceMode", "generalPurpose"),
                "throughput_mode": fs.get("ThroughputMode", "bursting"),
                "encrypted": fs.get("Encrypted", False),
                "kms_key_id": fs.get("KmsKeyId", ""),
                "tags": {t["Key"]: t["Value"] for t in fs.get("Tags", [])},
            })
        return file_systems

    def discover_ebs(self) -> list:
        volumes = []
        resp = self.ec2.describe_volumes(Filters=[{"Name": "status", "Values": ["available", "in-use"]}])
        for v in resp.get("Volumes", []):
            volumes.append({
                "id": v["VolumeId"],
                "type": v.get("VolumeType", "gp2"),
                "size": v["Size"],
                "az": v["AvailabilityZone"],
                "encrypted": v.get("Encrypted", False),
                "iops": v.get("Iops"),
                "throughput": v.get("Throughput"),
                "kms_key_id": v.get("KmsKeyId", ""),
                "attachments": [{"instance_id": a["InstanceId"], "device": a["Device"]} for a in v.get("Attachments", [])],
                "tags": self._tags(v),
            })
        return volumes

    # ── App, API & messaging ──────────────────────────────────────────────────

    def discover_rest_apis(self) -> list:
        apis = []
        resp = self.apigateway.get_rest_apis()
        for api in resp.get("items", []):
            apis.append({
                "id": api["id"], "name": api["name"],
                "description": api.get("description", ""),
                "endpoint_type": api.get("endpointConfiguration", {}).get("types", ["REGIONAL"])[0],
                "tags": api.get("tags", {}),
            })
        return apis

    def discover_http_apis(self) -> list:
        apis = []
        resp = self.apigatewayv2.get_apis()
        for api in resp.get("Items", []):
            apis.append({
                "id": api["ApiId"], "name": api["Name"],
                "protocol_type": api.get("ProtocolType", "HTTP"),
                "description": api.get("Description", ""),
                "cors_configuration": api.get("CorsConfiguration", {}),
                "tags": api.get("Tags", {}),
            })
        return apis

    def discover_cloudfront(self) -> list:
        distributions = []
        resp = self.cloudfront.list_distributions()
        items = resp.get("DistributionList", {}).get("Items", [])
        for d in items:
            origins = [{"domain": o["DomainName"], "id": o["Id"]} for o in d.get("Origins", {}).get("Items", [])]
            distributions.append({
                "id": d["Id"],
                "domain_name": d.get("DomainName", ""),
                "enabled": d.get("Enabled", True),
                "origins": origins,
                "default_root_object": d.get("DefaultRootObject", ""),
                "price_class": d.get("PriceClass", "PriceClass_All"),
                "aliases": d.get("Aliases", {}).get("Items", []),
                "viewer_protocol_policy": d.get("DefaultCacheBehavior", {}).get("ViewerProtocolPolicy", "redirect-to-https"),
                "https_only": d.get("DefaultCacheBehavior", {}).get("ViewerProtocolPolicy") == "https-only",
            })
        return distributions

    def discover_route53(self) -> list:
        zones = []
        paginator = self.route53.get_paginator("list_hosted_zones")
        for page in paginator.paginate():
            for zone in page["HostedZones"]:
                zones.append({
                    "id": zone["Id"].split("/")[-1],
                    "name": zone["Name"].rstrip("."),
                    "private": zone["Config"].get("PrivateZone", False),
                    "comment": zone["Config"].get("Comment", ""),
                    "record_count": zone.get("ResourceRecordSetCount", 0),
                })
        return zones

    def discover_acm(self) -> list:
        certs = []
        paginator = self.acm.get_paginator("list_certificates")
        for page in paginator.paginate(CertificateStatuses=["ISSUED"]):
            for c in page["CertificateSummaryList"]:
                detail = self.acm.describe_certificate(CertificateArn=c["CertificateArn"])["Certificate"]
                certs.append({
                    "arn": c["CertificateArn"],
                    "domain": detail.get("DomainName", ""),
                    "san": detail.get("SubjectAlternativeNames", []),
                    "validation_method": detail.get("DomainValidationOptions", [{}])[0].get("ValidationMethod", "DNS"),
                    "status": detail.get("Status", ""),
                })
        return certs

    def discover_sns(self) -> list:
        topics = []
        paginator = self.sns.get_paginator("list_topics")
        for page in paginator.paginate():
            for t in page["Topics"]:
                arn = t["TopicArn"]
                attrs = self.sns.get_topic_attributes(TopicArn=arn).get("Attributes", {})
                topics.append({
                    "arn": arn,
                    "name": arn.split(":")[-1],
                    "display_name": attrs.get("DisplayName", ""),
                    "fifo": arn.endswith(".fifo"),
                    "kms_key_id": attrs.get("KmsMasterKeyId", ""),
                })
        return topics

    def discover_sqs(self) -> list:
        queues = []
        urls = self.sqs.list_queues().get("QueueUrls", [])
        for url in urls:
            attrs = self.sqs.get_queue_attributes(
                QueueUrl=url,
                AttributeNames=["All"]
            ).get("Attributes", {})
            queues.append({
                "url": url,
                "name": url.split("/")[-1],
                "arn": attrs.get("QueueArn", ""),
                "visibility_timeout": int(attrs.get("VisibilityTimeout", 30)),
                "message_retention": int(attrs.get("MessageRetentionPeriod", 345600)),
                "delay_seconds": int(attrs.get("DelaySeconds", 0)),
                "max_message_size": int(attrs.get("MaximumMessageSize", 262144)),
                "fifo": url.endswith(".fifo"),
                "kms_key_id": attrs.get("KmsMasterKeyId", ""),
                "dlq_arn": attrs.get("RedrivePolicy", ""),
            })
        return queues

    def discover_kinesis(self) -> list:
        streams = []
        names = self.kinesis.list_streams().get("StreamNames", [])
        for name in names:
            desc = self.kinesis.describe_stream(StreamName=name)["StreamDescription"]
            streams.append({
                "name": name,
                "arn": desc.get("StreamARN", ""),
                "shard_count": len(desc.get("Shards", [])),
                "retention_period": desc.get("RetentionPeriodHours", 24),
                "encryption_type": desc.get("EncryptionType", "NONE"),
                "key_id": desc.get("KeyId", ""),
            })
        return streams

    def discover_eventbridge(self) -> list:
        rules = []
        paginator = self.events.get_paginator("list_rules")
        for page in paginator.paginate():
            for r in page["Rules"]:
                rules.append({
                    "name": r["Name"],
                    "arn": r.get("Arn", ""),
                    "schedule": r.get("ScheduleExpression", ""),
                    "event_pattern": r.get("EventPattern", ""),
                    "state": r.get("State", "ENABLED"),
                    "description": r.get("Description", ""),
                    "role_arn": r.get("RoleArn", ""),
                })
        return rules

    # ── Security, monitoring & DevOps ────────────────────────────────────────

    def discover_secrets(self) -> list:
        secrets = []
        paginator = self.secretsmanager.get_paginator("list_secrets")
        for page in paginator.paginate():
            for s in page["SecretList"]:
                secrets.append({
                    "name": s["Name"],
                    "arn": s["ARN"],
                    "description": s.get("Description", ""),
                    "kms_key_id": s.get("KmsKeyId", ""),
                    "rotation_enabled": s.get("RotationEnabled", False),
                    "rotation_lambda_arn": s.get("RotationLambdaARN", ""),
                    "tags": {t["Key"]: t["Value"] for t in s.get("Tags", [])},
                })
        return secrets

    def discover_kms(self) -> list:
        keys = []
        paginator = self.kms.get_paginator("list_keys")
        for page in paginator.paginate():
            for k in page["Keys"]:
                try:
                    meta = self.kms.describe_key(KeyId=k["KeyId"])["KeyMetadata"]
                    if meta.get("KeyManager") == "AWS" or meta.get("KeyState") != "Enabled":
                        continue
                    keys.append({
                        "id": meta["KeyId"],
                        "arn": meta["Arn"],
                        "description": meta.get("Description", ""),
                        "enabled": meta.get("Enabled", True),
                        "key_usage": meta.get("KeyUsage", "ENCRYPT_DECRYPT"),
                        "deletion_window": 30,
                        "multi_region": meta.get("MultiRegion", False),
                    })
                except ClientError:
                    pass
        return keys

    def discover_cloudwatch_alarms(self) -> list:
        alarms = []
        paginator = self.cloudwatch.get_paginator("describe_alarms")
        for page in paginator.paginate(AlarmTypes=["MetricAlarm"]):
            for a in page["MetricAlarms"]:
                alarms.append({
                    "name": a["AlarmName"],
                    "description": a.get("AlarmDescription", ""),
                    "metric_name": a.get("MetricName", ""),
                    "namespace": a.get("Namespace", ""),
                    "statistic": a.get("Statistic", "Average"),
                    "period": a.get("Period", 300),
                    "evaluation_periods": a.get("EvaluationPeriods", 1),
                    "threshold": a.get("Threshold", 0),
                    "comparison_operator": a.get("ComparisonOperator", "GreaterThanThreshold"),
                    "alarm_actions": a.get("AlarmActions", []),
                    "ok_actions": a.get("OKActions", []),
                    "dimensions": {d["Name"]: d["Value"] for d in a.get("Dimensions", [])},
                })
        return alarms

    def discover_log_groups(self) -> list:
        groups = []
        paginator = self.logs.get_paginator("describe_log_groups")
        for page in paginator.paginate():
            for g in page["logGroups"]:
                groups.append({
                    "name": g["logGroupName"],
                    "retention_days": g.get("retentionInDays"),
                    "kms_key_id": g.get("kmsKeyId", ""),
                    "stored_bytes": g.get("storedBytes", 0),
                })
        return groups

    def discover_codepipelines(self) -> list:
        pipelines = []
        paginator = self.codepipeline.get_paginator("list_pipelines")
        for page in paginator.paginate():
            for p in page["pipelines"]:
                detail = self.codepipeline.get_pipeline(name=p["name"])["pipeline"]
                pipelines.append({
                    "name": detail["name"],
                    "role_arn": detail.get("roleArn", ""),
                    "artifact_store": detail.get("artifactStore", {}),
                    "stages": [{"name": s["name"], "actions": len(s.get("actions", []))} for s in detail.get("stages", [])],
                })
        return pipelines

    def discover_codebuild(self) -> list:
        projects = []
        names = self.codebuild.list_projects().get("projects", [])
        if not names:
            return []
        for proj in self.codebuild.batch_get_projects(names=names)["projects"]:
            env = proj.get("environment", {})
            projects.append({
                "name": proj["name"],
                "description": proj.get("description", ""),
                "service_role": proj.get("serviceRole", ""),
                "build_timeout": proj.get("timeoutInMinutes", 60),
                "compute_type": env.get("computeType", "BUILD_GENERAL1_SMALL"),
                "image": env.get("image", ""),
                "environment_type": env.get("type", "LINUX_CONTAINER"),
                "source_type": proj.get("source", {}).get("type", ""),
                "source_location": proj.get("source", {}).get("location", ""),
                "artifacts_type": proj.get("artifacts", {}).get("type", "NO_ARTIFACTS"),
            })
        return projects

    def discover_waf(self) -> list:
        acls = []
        for scope in ["REGIONAL", "CLOUDFRONT"]:
            try:
                resp = self.wafv2.list_web_acls(Scope=scope)
                for acl in resp.get("WebACLs", []):
                    acls.append({
                        "id": acl["Id"],
                        "name": acl["Name"],
                        "arn": acl["ARN"],
                        "scope": scope,
                        "description": acl.get("Description", ""),
                    })
            except ClientError:
                pass
        return acls

    def discover_albs(self) -> list:
        lbs = []
        for lb in self.elbv2.describe_load_balancers().get("LoadBalancers", []):
            lbs.append({
                "name": lb["LoadBalancerName"], "arn": lb["LoadBalancerArn"],
                "type": lb["Type"], "scheme": lb["Scheme"],
                "vpc_id": lb.get("VpcId"),
                "subnets": [az["SubnetId"] for az in lb.get("AvailabilityZones", [])],
                "security_groups": lb.get("SecurityGroups", []),
            })
        return lbs

    def discover_iam_roles(self) -> list:
        roles = []
        paginator = self.iam.get_paginator("list_roles")
        for page in paginator.paginate():
            for r in page["Roles"]:
                if "aws-service-role" in r["Path"]:
                    continue
                attached = self.iam.list_attached_role_policies(RoleName=r["RoleName"])
                roles.append({
                    "name": r["RoleName"], "path": r["Path"],
                    "assume_role_policy": r["AssumeRolePolicyDocument"],
                    "attached_policies": [p["PolicyArn"] for p in attached.get("AttachedPolicies", [])],
                })
        return roles

    def discover_asg(self) -> list:
        groups = []
        for asg in self.autoscaling.describe_auto_scaling_groups()["AutoScalingGroups"]:
            groups.append({
                "name": asg["AutoScalingGroupName"],
                "min_size": asg["MinSize"], "max_size": asg["MaxSize"],
                "desired": asg["DesiredCapacity"],
                "subnets": asg.get("VPCZoneIdentifier", "").split(","),
                "launch_config": asg.get("LaunchConfigurationName", ""),
            })
        return groups

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _tags(self, resource: dict) -> dict:
        return {t["Key"]: t["Value"] for t in resource.get("Tags", [])}

    def _vpc_attr(self, vpc_id: str, attr: str) -> bool:
        try:
            resp = self.ec2.describe_vpc_attribute(VpcId=vpc_id, Attribute=attr)
            return resp.get(attr, {}).get("Value", False)
        except ClientError:
            return False
