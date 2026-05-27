import json
import yaml
from utils.helpers import slugify, tags_to_cfn


class CloudFormationGenerator:
    def __init__(self, resources: dict, region: str):
        self.resources = resources
        self.region = region

    def generate(self) -> str:
        template = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": f"CloudFormation template generated from live AWS infrastructure in {self.region}",
            "Parameters": self._parameters(),
            "Resources": {},
            "Outputs": {},
        }

        template["Resources"].update(self._vpcs())
        template["Resources"].update(self._subnets())
        template["Resources"].update(self._igws())
        template["Resources"].update(self._route_tables())
        template["Resources"].update(self._security_groups())
        template["Resources"].update(self._ec2_instances())
        template["Resources"].update(self._s3_buckets())
        template["Resources"].update(self._rds_instances())
        template["Resources"].update(self._iam_roles())
        template["Resources"].update(self._load_balancers())

        template["Outputs"] = self._outputs(template["Resources"])

        if not template["Parameters"]:
            del template["Parameters"]

        return yaml.dump(template, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def _parameters(self) -> dict:
        params = {}
        for db in self.resources.get("rds_instances", []):
            slug = slugify(db["id"])
            params[f"{slug}Password"] = {
                "Type": "String",
                "NoEcho": True,
                "Description": f"Master password for RDS instance {db['id']}",
            }
        return params

    def _logical_id(self, raw: str, prefix: str = "") -> str:
        slug = slugify(raw).replace("_", "").replace("-", "")
        return f"{prefix}{slug[:60].capitalize()}"

    def _vpcs(self) -> dict:
        result = {}
        for vpc in self.resources.get("vpcs", []):
            lid = self._logical_id(vpc["tags"].get("Name", vpc["id"]), "VPC")
            result[lid] = {
                "Type": "AWS::EC2::VPC",
                "Properties": {
                    "CidrBlock": vpc["cidr"],
                    "EnableDnsSupport": vpc["enable_dns_support"],
                    "EnableDnsHostnames": vpc["enable_dns_hostnames"],
                    "Tags": tags_to_cfn(vpc["tags"]) or [{"Key": "Name", "Value": vpc["tags"].get("Name", vpc["id"])}],
                },
            }
        return result

    def _subnets(self) -> dict:
        result = {}
        for s in self.resources.get("subnets", []):
            lid = self._logical_id(s["tags"].get("Name", s["id"]), "Subnet")
            result[lid] = {
                "Type": "AWS::EC2::Subnet",
                "Properties": {
                    "VpcId": s["vpc_id"],
                    "CidrBlock": s["cidr"],
                    "AvailabilityZone": s["az"],
                    "MapPublicIpOnLaunch": s["map_public_ip"],
                    "Tags": tags_to_cfn(s["tags"]) or [{"Key": "Name", "Value": s["tags"].get("Name", s["id"])}],
                },
            }
        return result

    def _igws(self) -> dict:
        result = {}
        for igw in self.resources.get("internet_gateways", []):
            lid = self._logical_id(igw["tags"].get("Name", igw["id"]), "IGW")
            result[lid] = {
                "Type": "AWS::EC2::InternetGateway",
                "Properties": {
                    "Tags": tags_to_cfn(igw["tags"]) or [{"Key": "Name", "Value": igw["id"]}],
                },
            }
            if igw.get("vpc_id"):
                attach_lid = f"{lid}Attachment"
                result[attach_lid] = {
                    "Type": "AWS::EC2::VPCGatewayAttachment",
                    "Properties": {
                        "VpcId": igw["vpc_id"],
                        "InternetGatewayId": {"Ref": lid},
                    },
                }
        return result

    def _route_tables(self) -> dict:
        result = {}
        for rt in self.resources.get("route_tables", []):
            lid = self._logical_id(rt["tags"].get("Name", rt["id"]), "RT")
            result[lid] = {
                "Type": "AWS::EC2::RouteTable",
                "Properties": {
                    "VpcId": rt["vpc_id"],
                    "Tags": tags_to_cfn(rt["tags"]) or [{"Key": "Name", "Value": rt["id"]}],
                },
            }
            for idx, r in enumerate(rt["routes"]):
                if not r["cidr"] or r["cidr"] == "local":
                    continue
                route_lid = f"{lid}Route{idx}"
                route_props = {
                    "RouteTableId": {"Ref": lid},
                    "DestinationCidrBlock": r["cidr"],
                }
                if r.get("gateway_id"):
                    route_props["GatewayId"] = r["gateway_id"]
                elif r.get("nat_gateway_id"):
                    route_props["NatGatewayId"] = r["nat_gateway_id"]
                result[route_lid] = {"Type": "AWS::EC2::Route", "Properties": route_props}

            for idx, subnet_id in enumerate(rt.get("subnet_associations", [])):
                assoc_lid = f"{lid}Assoc{idx}"
                result[assoc_lid] = {
                    "Type": "AWS::EC2::SubnetRouteTableAssociation",
                    "Properties": {"SubnetId": subnet_id, "RouteTableId": {"Ref": lid}},
                }
        return result

    def _security_groups(self) -> dict:
        result = {}
        for sg in self.resources.get("security_groups", []):
            if sg["name"] == "default":
                continue
            lid = self._logical_id(sg["name"], "SG")
            ingress = []
            for rule in sg.get("ingress", []):
                proto = rule.get("IpProtocol", "-1")
                for cidr in rule.get("IpRanges", []):
                    ingress.append({
                        "IpProtocol": proto,
                        "FromPort": rule.get("FromPort", -1),
                        "ToPort": rule.get("ToPort", -1),
                        "CidrIp": cidr["CidrIp"],
                    })
            egress = []
            for rule in sg.get("egress", []):
                proto = rule.get("IpProtocol", "-1")
                for cidr in rule.get("IpRanges", []):
                    egress.append({
                        "IpProtocol": proto,
                        "FromPort": rule.get("FromPort", -1),
                        "ToPort": rule.get("ToPort", -1),
                        "CidrIp": cidr["CidrIp"],
                    })
            props = {
                "GroupName": sg["name"],
                "GroupDescription": sg["description"],
                "Tags": tags_to_cfn(sg.get("tags", {})) or [{"Key": "Name", "Value": sg["name"]}],
            }
            if sg.get("vpc_id"):
                props["VpcId"] = sg["vpc_id"]
            if ingress:
                props["SecurityGroupIngress"] = ingress
            if egress:
                props["SecurityGroupEgress"] = egress
            result[lid] = {"Type": "AWS::EC2::SecurityGroup", "Properties": props}
        return result

    def _ec2_instances(self) -> dict:
        result = {}
        for i in self.resources.get("ec2_instances", []):
            name = i["tags"].get("Name", i["id"])
            lid = self._logical_id(name, "EC2")
            props = {
                "ImageId": i["ami"],
                "InstanceType": i["type"],
                "SubnetId": i.get("subnet_id", ""),
                "SecurityGroupIds": i.get("security_groups", []),
                "EbsOptimized": i.get("ebs_optimized", False),
                "Monitoring": {"Enabled": i.get("monitoring", False)},
                "Tags": tags_to_cfn(i["tags"]) or [{"Key": "Name", "Value": name}],
            }
            if i.get("key_name"):
                props["KeyName"] = i["key_name"]
            if i.get("iam_profile"):
                props["IamInstanceProfile"] = i["iam_profile"].split("/")[-1]
            result[lid] = {"Type": "AWS::EC2::Instance", "Properties": props}
        return result

    def _s3_buckets(self) -> dict:
        result = {}
        for b in self.resources.get("s3_buckets", []):
            lid = self._logical_id(b["name"], "S3")
            props = {"BucketName": b["name"]}
            if b.get("versioning"):
                props["VersioningConfiguration"] = {"Status": "Enabled"}
            if b.get("encryption"):
                props["BucketEncryption"] = {
                    "ServerSideEncryptionConfiguration": [{
                        "ServerSideEncryptionByDefault": {"SSEAlgorithm": b["encryption"]}
                    }]
                }
            result[lid] = {"Type": "AWS::S3::Bucket", "Properties": props}
        return result

    def _rds_instances(self) -> dict:
        result = {}
        for db in self.resources.get("rds_instances", []):
            lid = self._logical_id(db["id"], "RDS")
            slug = slugify(db["id"])
            props = {
                "DBInstanceIdentifier": db["id"],
                "Engine": db["engine"],
                "EngineVersion": db["engine_version"],
                "DBInstanceClass": db["instance_class"],
                "AllocatedStorage": str(db["allocated_storage"]),
                "MasterUsername": db["username"],
                "MasterUserPassword": {"Ref": f"{slug}Password"},
                "MultiAZ": db["multi_az"],
                "PubliclyAccessible": db["publicly_accessible"],
                "VPCSecurityGroups": db.get("security_groups", []),
            }
            if db.get("db_name"):
                props["DBName"] = db["db_name"]
            if db.get("subnet_group"):
                props["DBSubnetGroupName"] = db["subnet_group"]
            result[lid] = {"Type": "AWS::RDS::DBInstance", "Properties": props}
        return result

    def _iam_roles(self) -> dict:
        result = {}
        for role in self.resources.get("iam_roles", []):
            lid = self._logical_id(role["name"], "Role")
            result[lid] = {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "RoleName": role["name"],
                    "Path": role["path"],
                    "AssumeRolePolicyDocument": role["assume_role_policy"],
                    "ManagedPolicyArns": role.get("attached_policies", []),
                },
            }
        return result

    def _load_balancers(self) -> dict:
        result = {}
        for lb in self.resources.get("load_balancers", []):
            lid = self._logical_id(lb["name"], "ALB")
            result[lid] = {
                "Type": "AWS::ElasticLoadBalancingV2::LoadBalancer",
                "Properties": {
                    "Name": lb["name"],
                    "Type": lb["type"],
                    "Scheme": lb.get("scheme", "internet-facing"),
                    "Subnets": lb.get("subnets", []),
                    "SecurityGroups": lb.get("security_groups", []),
                },
            }
        return result

    def _outputs(self, resources: dict) -> dict:
        outputs = {}
        for lid, resource in resources.items():
            rtype = resource.get("Type", "")
            if rtype in ("AWS::EC2::VPC", "AWS::S3::Bucket", "AWS::RDS::DBInstance", "AWS::ElasticLoadBalancingV2::LoadBalancer"):
                outputs[f"{lid}Id"] = {
                    "Description": f"{lid} resource ID",
                    "Value": {"Ref": lid},
                    "Export": {"Name": {"Fn::Sub": f"${{AWS::StackName}}-{lid}"}},
                }
        return outputs
