import boto3
from botocore.exceptions import ClientError
from rich.console import Console

console = Console()


class AWSDiscoverer:
    def __init__(self, region: str, profile: str = None):
        self.region = region
        session = boto3.Session(profile_name=profile, region_name=region) if profile else boto3.Session(region_name=region)
        self.ec2 = session.client("ec2")
        self.s3 = session.client("s3")
        self.rds = session.client("rds")
        self.iam = session.client("iam")
        self.elbv2 = session.client("elbv2")
        self.autoscaling = session.client("autoscaling")

    def discover_all(self) -> dict:
        console.print("[bold cyan]Discovering AWS infrastructure...[/bold cyan]")
        resources = {}

        steps = [
            ("vpcs", self.discover_vpcs),
            ("subnets", self.discover_subnets),
            ("internet_gateways", self.discover_igws),
            ("route_tables", self.discover_route_tables),
            ("security_groups", self.discover_security_groups),
            ("ec2_instances", self.discover_ec2),
            ("s3_buckets", self.discover_s3),
            ("rds_instances", self.discover_rds),
            ("iam_roles", self.discover_iam_roles),
            ("load_balancers", self.discover_albs),
            ("auto_scaling_groups", self.discover_asg),
        ]

        for name, fn in steps:
            try:
                console.print(f"  [yellow]→[/yellow] Scanning {name}...")
                resources[name] = fn()
                console.print(f"  [green]✓[/green] Found {len(resources[name])} {name}")
            except ClientError as e:
                console.print(f"  [red]✗[/red] {name}: {e.response['Error']['Message']}")
                resources[name] = []

        return resources

    def discover_vpcs(self) -> list:
        vpcs = []
        resp = self.ec2.describe_vpcs()
        for v in resp["Vpcs"]:
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
        subnets = []
        resp = self.ec2.describe_subnets()
        for s in resp["Subnets"]:
            subnets.append({
                "id": s["SubnetId"],
                "vpc_id": s["VpcId"],
                "cidr": s["CidrBlock"],
                "az": s["AvailabilityZone"],
                "map_public_ip": s.get("MapPublicIpOnLaunch", False),
                "tags": self._tags(s),
            })
        return subnets

    def discover_igws(self) -> list:
        igws = []
        resp = self.ec2.describe_internet_gateways()
        for igw in resp["InternetGateways"]:
            attachments = igw.get("Attachments", [])
            igws.append({
                "id": igw["InternetGatewayId"],
                "vpc_id": attachments[0]["VpcId"] if attachments else None,
                "tags": self._tags(igw),
            })
        return igws

    def discover_route_tables(self) -> list:
        rts = []
        resp = self.ec2.describe_route_tables()
        for rt in resp["RouteTables"]:
            routes = []
            for r in rt.get("Routes", []):
                routes.append({
                    "cidr": r.get("DestinationCidrBlock", ""),
                    "gateway_id": r.get("GatewayId"),
                    "nat_gateway_id": r.get("NatGatewayId"),
                    "instance_id": r.get("InstanceId"),
                })
            associations = [a["SubnetId"] for a in rt.get("Associations", []) if "SubnetId" in a]
            rts.append({
                "id": rt["RouteTableId"],
                "vpc_id": rt["VpcId"],
                "routes": routes,
                "subnet_associations": associations,
                "tags": self._tags(rt),
            })
        return rts

    def discover_security_groups(self) -> list:
        sgs = []
        resp = self.ec2.describe_security_groups()
        for sg in resp["SecurityGroups"]:
            sgs.append({
                "id": sg["GroupId"],
                "name": sg["GroupName"],
                "description": sg["Description"],
                "vpc_id": sg.get("VpcId"),
                "ingress": sg.get("IpPermissions", []),
                "egress": sg.get("IpPermissionsEgress", []),
                "tags": self._tags(sg),
            })
        return sgs

    def discover_ec2(self) -> list:
        instances = []
        resp = self.ec2.describe_instances()
        for reservation in resp["Reservations"]:
            for i in reservation["Instances"]:
                if i["State"]["Name"] == "terminated":
                    continue
                instances.append({
                    "id": i["InstanceId"],
                    "type": i["InstanceType"],
                    "ami": i["ImageId"],
                    "subnet_id": i.get("SubnetId"),
                    "vpc_id": i.get("VpcId"),
                    "key_name": i.get("KeyName"),
                    "iam_profile": i.get("IamInstanceProfile", {}).get("Arn", ""),
                    "security_groups": [sg["GroupId"] for sg in i.get("SecurityGroups", [])],
                    "public_ip": i.get("PublicIpAddress"),
                    "private_ip": i.get("PrivateIpAddress"),
                    "ebs_optimized": i.get("EbsOptimized", False),
                    "monitoring": i.get("Monitoring", {}).get("State") == "enabled",
                    "root_volume": self._root_volume(i),
                    "tags": self._tags(i),
                })
        return instances

    def discover_s3(self) -> list:
        buckets = []
        resp = self.s3.list_buckets()
        for b in resp.get("Buckets", []):
            name = b["Name"]
            bucket = {"name": name, "versioning": False, "encryption": None, "acl": "private"}
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
        resp = self.rds.describe_db_instances()
        for db in resp["DBInstances"]:
            instances.append({
                "id": db["DBInstanceIdentifier"],
                "engine": db["Engine"],
                "engine_version": db["EngineVersion"],
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

    def discover_iam_roles(self) -> list:
        roles = []
        paginator = self.iam.get_paginator("list_roles")
        for page in paginator.paginate():
            for r in page["Roles"]:
                if "aws-service-role" in r["Path"]:
                    continue
                policies = []
                attached = self.iam.list_attached_role_policies(RoleName=r["RoleName"])
                policies = [p["PolicyArn"] for p in attached.get("AttachedPolicies", [])]
                roles.append({
                    "name": r["RoleName"],
                    "path": r["Path"],
                    "assume_role_policy": r["AssumeRolePolicyDocument"],
                    "attached_policies": policies,
                })
        return roles

    def discover_albs(self) -> list:
        lbs = []
        resp = self.elbv2.describe_load_balancers()
        for lb in resp["LoadBalancers"]:
            lbs.append({
                "name": lb["LoadBalancerName"],
                "arn": lb["LoadBalancerArn"],
                "type": lb["Type"],
                "scheme": lb["Scheme"],
                "vpc_id": lb.get("VpcId"),
                "subnets": [az["SubnetId"] for az in lb.get("AvailabilityZones", [])],
                "security_groups": lb.get("SecurityGroups", []),
            })
        return lbs

    def discover_asg(self) -> list:
        groups = []
        resp = self.autoscaling.describe_auto_scaling_groups()
        for asg in resp["AutoScalingGroups"]:
            groups.append({
                "name": asg["AutoScalingGroupName"],
                "min_size": asg["MinSize"],
                "max_size": asg["MaxSize"],
                "desired": asg["DesiredCapacity"],
                "subnets": asg.get("VPCZoneIdentifier", "").split(","),
                "launch_config": asg.get("LaunchConfigurationName", ""),
            })
        return groups

    def _tags(self, resource: dict) -> dict:
        return {t["Key"]: t["Value"] for t in resource.get("Tags", [])}

    def _vpc_attr(self, vpc_id: str, attr: str) -> bool:
        try:
            resp = self.ec2.describe_vpc_attribute(VpcId=vpc_id, Attribute=attr)
            return resp.get(attr, {}).get("Value", False)
        except ClientError:
            return False

    def _root_volume(self, instance: dict) -> dict:
        for mapping in instance.get("BlockDeviceMappings", []):
            if mapping.get("DeviceName") == instance.get("RootDeviceName"):
                return {"volume_id": mapping["Ebs"].get("VolumeId", ""), "delete_on_termination": mapping["Ebs"].get("DeleteOnTermination", True)}
        return {}
