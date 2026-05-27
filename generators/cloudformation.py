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
        for section in [
            self._vpcs(), self._subnets(), self._igws(),
            self._nat_gateways(), self._eips(), self._route_tables(),
            self._security_groups(), self._nacls(),
            self._vpc_peering(), self._vpc_endpoints(),
            self._ec2_instances(), self._lambda_functions(),
            self._ecs_clusters(), self._ecs_task_definitions(), self._ecs_services(),
            self._eks_clusters(), self._ecr_repos(),
            self._s3_buckets(), self._rds_instances(),
            self._dynamodb_tables(), self._elasticache_clusters(),
            self._efs_file_systems(),
            self._rest_apis(), self._http_apis(),
            self._cloudfront_distributions(), self._route53_zones(),
            self._acm_certificates(), self._sns_topics(), self._sqs_queues(),
            self._kinesis_streams(), self._eventbridge_rules(),
            self._secrets(), self._kms_keys(),
            self._cloudwatch_alarms(), self._log_groups(),
            self._codepipelines(), self._codebuild_projects(), self._waf_acls(),
            self._load_balancers(), self._iam_roles(),
        ]:
            template["Resources"].update(section)

        template["Outputs"] = self._outputs(template["Resources"])
        if not template["Parameters"]:
            del template["Parameters"]

        return yaml.dump(template, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def _lid(self, value: str, prefix: str = "") -> str:
        slug = slugify(value).replace("_", "").replace("-", "")
        return f"{prefix}{slug[:60].capitalize()}"

    def _parameters(self) -> dict:
        params = {}
        for db in self.resources.get("rds_instances", []):
            slug = slugify(db["id"])
            params[f"{slug}Password"] = {
                "Type": "String", "NoEcho": True,
                "Description": f"Master password for RDS instance {db['id']}",
            }
        return params

    # ── Networking ────────────────────────────────────────────────────────────

    def _vpcs(self) -> dict:
        return {
            self._lid(v["tags"].get("Name", v["id"]), "VPC"): {
                "Type": "AWS::EC2::VPC",
                "Properties": {
                    "CidrBlock": v["cidr"],
                    "EnableDnsSupport": v["enable_dns_support"],
                    "EnableDnsHostnames": v["enable_dns_hostnames"],
                    "Tags": tags_to_cfn(v["tags"]) or [{"Key": "Name", "Value": v["id"]}],
                },
            }
            for v in self.resources.get("vpcs", [])
        }

    def _subnets(self) -> dict:
        return {
            self._lid(s["tags"].get("Name", s["id"]), "Subnet"): {
                "Type": "AWS::EC2::Subnet",
                "Properties": {
                    "VpcId": s["vpc_id"],
                    "CidrBlock": s["cidr"],
                    "AvailabilityZone": s["az"],
                    "MapPublicIpOnLaunch": s["map_public_ip"],
                    "Tags": tags_to_cfn(s["tags"]) or [{"Key": "Name", "Value": s["id"]}],
                },
            }
            for s in self.resources.get("subnets", [])
        }

    def _igws(self) -> dict:
        result = {}
        for igw in self.resources.get("internet_gateways", []):
            lid = self._lid(igw["tags"].get("Name", igw["id"]), "IGW")
            result[lid] = {
                "Type": "AWS::EC2::InternetGateway",
                "Properties": {"Tags": tags_to_cfn(igw["tags"]) or [{"Key": "Name", "Value": igw["id"]}]},
            }
            if igw.get("vpc_id"):
                result[f"{lid}Attachment"] = {
                    "Type": "AWS::EC2::VPCGatewayAttachment",
                    "Properties": {"VpcId": igw["vpc_id"], "InternetGatewayId": {"Ref": lid}},
                }
        return result

    def _nat_gateways(self) -> dict:
        result = {}
        for nat in self.resources.get("nat_gateways", []):
            lid = self._lid(nat["tags"].get("Name", nat["id"]), "NAT")
            props = {
                "SubnetId": nat["subnet_id"],
                "ConnectivityType": nat.get("connectivity_type", "public"),
                "Tags": tags_to_cfn(nat["tags"]) or [{"Key": "Name", "Value": nat["id"]}],
            }
            if nat.get("eip_allocation_id") and nat.get("connectivity_type", "public") == "public":
                props["AllocationId"] = nat["eip_allocation_id"]
            result[lid] = {"Type": "AWS::EC2::NatGateway", "Properties": props}
        return result

    def _eips(self) -> dict:
        return {
            self._lid(e["allocation_id"], "EIP"): {
                "Type": "AWS::EC2::EIP",
                "Properties": {"Domain": e.get("domain", "vpc")},
            }
            for e in self.resources.get("elastic_ips", [])
        }

    def _route_tables(self) -> dict:
        result = {}
        for rt in self.resources.get("route_tables", []):
            lid = self._lid(rt["tags"].get("Name", rt["id"]), "RT")
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
                route_props = {"RouteTableId": {"Ref": lid}, "DestinationCidrBlock": r["cidr"]}
                if r.get("gateway_id"):
                    route_props["GatewayId"] = r["gateway_id"]
                elif r.get("nat_gateway_id"):
                    route_props["NatGatewayId"] = r["nat_gateway_id"]
                result[f"{lid}Route{idx}"] = {"Type": "AWS::EC2::Route", "Properties": route_props}
            for idx, subnet_id in enumerate(rt.get("subnet_associations", [])):
                result[f"{lid}Assoc{idx}"] = {
                    "Type": "AWS::EC2::SubnetRouteTableAssociation",
                    "Properties": {"SubnetId": subnet_id, "RouteTableId": {"Ref": lid}},
                }
        return result

    def _security_groups(self) -> dict:
        result = {}
        for sg in self.resources.get("security_groups", []):
            if sg["name"] == "default":
                continue
            lid = self._lid(sg["name"], "SG")
            ingress = []
            for rule in sg.get("ingress", []):
                proto = rule.get("IpProtocol", "-1")
                for cidr in rule.get("IpRanges", []):
                    ingress.append({"IpProtocol": proto, "FromPort": rule.get("FromPort", -1), "ToPort": rule.get("ToPort", -1), "CidrIp": cidr["CidrIp"]})
            egress = []
            for rule in sg.get("egress", []):
                proto = rule.get("IpProtocol", "-1")
                for cidr in rule.get("IpRanges", []):
                    egress.append({"IpProtocol": proto, "FromPort": rule.get("FromPort", -1), "ToPort": rule.get("ToPort", -1), "CidrIp": cidr["CidrIp"]})
            props = {
                "GroupName": sg["name"], "GroupDescription": sg["description"],
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

    def _nacls(self) -> dict:
        result = {}
        for acl in self.resources.get("network_acls", []):
            if acl.get("is_default"):
                continue
            lid = self._lid(acl["tags"].get("Name", acl["id"]), "NACL")
            result[lid] = {
                "Type": "AWS::EC2::NetworkAcl",
                "Properties": {
                    "VpcId": acl["vpc_id"],
                    "Tags": tags_to_cfn(acl["tags"]) or [{"Key": "Name", "Value": acl["id"]}],
                },
            }
            for idx, e in enumerate(acl.get("entries", [])):
                if e["rule_number"] >= 32767:
                    continue
                entry_props = {
                    "NetworkAclId": {"Ref": lid},
                    "RuleNumber": e["rule_number"],
                    "Protocol": e["protocol"],
                    "RuleAction": e["rule_action"],
                    "Egress": e["egress"],
                    "CidrBlock": e["cidr"],
                }
                if e.get("from_port") is not None:
                    entry_props["PortRange"] = {"From": e["from_port"], "To": e["to_port"]}
                result[f"{lid}Entry{idx}"] = {"Type": "AWS::EC2::NetworkAclEntry", "Properties": entry_props}
        return result

    def _vpc_peering(self) -> dict:
        return {
            self._lid(p["id"], "Peer"): {
                "Type": "AWS::EC2::VPCPeeringConnection",
                "Properties": {
                    "VpcId": p["requester_vpc_id"],
                    "PeerVpcId": p["accepter_vpc_id"],
                    "Tags": tags_to_cfn(p["tags"]) or [{"Key": "Name", "Value": p["id"]}],
                },
            }
            for p in self.resources.get("vpc_peering", [])
        }

    def _vpc_endpoints(self) -> dict:
        result = {}
        for ep in self.resources.get("vpc_endpoints", []):
            lid = self._lid(ep["id"], "Endpoint")
            props = {
                "VpcId": ep["vpc_id"],
                "ServiceName": ep["service_name"],
                "VpcEndpointType": ep.get("endpoint_type", "Gateway"),
            }
            if ep.get("route_table_ids"):
                props["RouteTableIds"] = ep["route_table_ids"]
            if ep.get("subnet_ids"):
                props["SubnetIds"] = ep["subnet_ids"]
            result[lid] = {"Type": "AWS::EC2::VPCEndpoint", "Properties": props}
        return result

    # ── Compute & containers ──────────────────────────────────────────────────

    def _ec2_instances(self) -> dict:
        result = {}
        for i in self.resources.get("ec2_instances", []):
            name = i["tags"].get("Name", i["id"])
            lid = self._lid(name, "EC2")
            props = {
                "ImageId": i["ami"], "InstanceType": i["type"],
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

    def _lambda_functions(self) -> dict:
        result = {}
        for fn in self.resources.get("lambda_functions", []):
            lid = self._lid(fn["name"], "Lambda")
            props = {
                "FunctionName": fn["name"],
                "Description": fn.get("description", ""),
                "Role": fn["role"],
                "Runtime": fn["runtime"],
                "Handler": fn["handler"],
                "MemorySize": fn.get("memory", 128),
                "Timeout": fn.get("timeout", 3),
                "Architectures": fn.get("architectures", ["x86_64"]),
                "Code": {"ZipFile": "# placeholder"},
            }
            if fn.get("environment"):
                props["Environment"] = {"Variables": fn["environment"]}
            if fn.get("subnet_ids") and fn.get("security_group_ids"):
                props["VpcConfig"] = {
                    "SubnetIds": fn["subnet_ids"],
                    "SecurityGroupIds": fn["security_group_ids"],
                }
            if fn.get("layers"):
                props["Layers"] = fn["layers"]
            result[lid] = {"Type": "AWS::Lambda::Function", "Properties": props}
        return result

    def _ecs_clusters(self) -> dict:
        return {
            self._lid(c["name"], "ECSCluster"): {
                "Type": "AWS::ECS::Cluster",
                "Properties": {
                    "ClusterName": c["name"],
                    "Tags": tags_to_cfn(c.get("tags", {})),
                },
            }
            for c in self.resources.get("ecs_clusters", [])
        }

    def _ecs_task_definitions(self) -> dict:
        result = {}
        for td in self.resources.get("ecs_task_definitions", []):
            lid = self._lid(td["family"], "ECSTaskDef")
            props = {
                "Family": td["family"],
                "NetworkMode": td.get("network_mode", "bridge"),
                "RequiresCompatibilities": td.get("requires_compatibilities", ["EC2"]),
                "ContainerDefinitions": td.get("container_definitions", []),
            }
            if td.get("cpu"):
                props["Cpu"] = td["cpu"]
            if td.get("memory"):
                props["Memory"] = td["memory"]
            if td.get("execution_role_arn"):
                props["ExecutionRoleArn"] = td["execution_role_arn"]
            if td.get("task_role_arn"):
                props["TaskRoleArn"] = td["task_role_arn"]
            result[lid] = {"Type": "AWS::ECS::TaskDefinition", "Properties": props}
        return result

    def _ecs_services(self) -> dict:
        result = {}
        for svc in self.resources.get("ecs_services", []):
            lid = self._lid(f"{svc['cluster']}_{svc['name']}", "ECSSvc")
            props = {
                "ServiceName": svc["name"],
                "Cluster": svc["cluster"],
                "TaskDefinition": svc.get("task_definition", ""),
                "DesiredCount": svc.get("desired_count", 1),
                "LaunchType": svc.get("launch_type", "FARGATE"),
            }
            if svc.get("subnets"):
                props["NetworkConfiguration"] = {
                    "AwsvpcConfiguration": {
                        "Subnets": svc["subnets"],
                        "SecurityGroups": svc.get("security_groups", []),
                        "AssignPublicIp": svc.get("assign_public_ip", "DISABLED"),
                    }
                }
            result[lid] = {"Type": "AWS::ECS::Service", "Properties": props}
        return result

    def _eks_clusters(self) -> dict:
        result = {}
        for c in self.resources.get("eks_clusters", []):
            lid = self._lid(c["name"], "EKS")
            result[lid] = {
                "Type": "AWS::EKS::Cluster",
                "Properties": {
                    "Name": c["name"],
                    "Version": c.get("version", ""),
                    "RoleArn": c.get("role_arn", ""),
                    "ResourcesVpcConfig": {
                        "SubnetIds": c.get("subnet_ids", []),
                        "SecurityGroupIds": c.get("security_group_ids", []),
                        "EndpointPublicAccess": c.get("endpoint_public_access", True),
                        "EndpointPrivateAccess": c.get("endpoint_private_access", False),
                    },
                    "Tags": tags_to_cfn(c.get("tags", {})),
                },
            }
        return result

    def _ecr_repos(self) -> dict:
        result = {}
        for r in self.resources.get("ecr_repositories", []):
            lid = self._lid(r["name"], "ECR")
            result[lid] = {
                "Type": "AWS::ECR::Repository",
                "Properties": {
                    "RepositoryName": r["name"],
                    "ImageTagMutability": r.get("image_tag_mutability", "MUTABLE"),
                    "ImageScanningConfiguration": {"ScanOnPush": r.get("scan_on_push", False)},
                    "EncryptionConfiguration": {"EncryptionType": r.get("encryption_type", "AES256")},
                },
            }
        return result

    # ── Storage & databases ───────────────────────────────────────────────────

    def _s3_buckets(self) -> dict:
        result = {}
        for b in self.resources.get("s3_buckets", []):
            lid = self._lid(b["name"], "S3")
            props = {"BucketName": b["name"]}
            if b.get("versioning"):
                props["VersioningConfiguration"] = {"Status": "Enabled"}
            if b.get("encryption"):
                props["BucketEncryption"] = {
                    "ServerSideEncryptionConfiguration": [{"ServerSideEncryptionByDefault": {"SSEAlgorithm": b["encryption"]}}]
                }
            result[lid] = {"Type": "AWS::S3::Bucket", "Properties": props}
        return result

    def _rds_instances(self) -> dict:
        result = {}
        for db in self.resources.get("rds_instances", []):
            lid = self._lid(db["id"], "RDS")
            slug = slugify(db["id"])
            props = {
                "DBInstanceIdentifier": db["id"],
                "Engine": db["engine"], "EngineVersion": db["engine_version"],
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

    def _dynamodb_tables(self) -> dict:
        result = {}
        for t in self.resources.get("dynamodb_tables", []):
            lid = self._lid(t["name"], "DDB")
            attrs = [{"AttributeName": k, "AttributeType": v} for k, v in t.get("attributes", {}).items()]
            key_schema = [{"AttributeName": t["hash_key"], "KeyType": "HASH"}]
            if t.get("range_key"):
                key_schema.append({"AttributeName": t["range_key"], "KeyType": "RANGE"})
            billing = t.get("billing_mode", "PROVISIONED")
            props = {
                "TableName": t["name"],
                "AttributeDefinitions": attrs,
                "KeySchema": key_schema,
                "BillingMode": billing,
            }
            if billing == "PROVISIONED":
                props["ProvisionedThroughput"] = {
                    "ReadCapacityUnits": t.get("read_capacity", 5),
                    "WriteCapacityUnits": t.get("write_capacity", 5),
                }
            if t.get("stream_enabled"):
                props["StreamSpecification"] = {"StreamViewType": t.get("stream_view_type", "NEW_AND_OLD_IMAGES")}
            gsis = []
            for gsi in t.get("global_secondary_indexes", []):
                gsi_key = [{"AttributeName": gsi["hash_key"], "KeyType": "HASH"}]
                if gsi.get("range_key"):
                    gsi_key.append({"AttributeName": gsi["range_key"], "KeyType": "RANGE"})
                gsis.append({
                    "IndexName": gsi["name"], "KeySchema": gsi_key,
                    "Projection": {"ProjectionType": gsi.get("projection_type", "ALL")},
                })
            if gsis:
                props["GlobalSecondaryIndexes"] = gsis
            result[lid] = {"Type": "AWS::DynamoDB::Table", "Properties": props}
        return result

    def _elasticache_clusters(self) -> dict:
        result = {}
        for c in self.resources.get("elasticache_clusters", []):
            lid = self._lid(c["id"], "Cache")
            result[lid] = {
                "Type": "AWS::ElastiCache::CacheCluster",
                "Properties": {
                    "ClusterId": c["id"],
                    "Engine": c["engine"],
                    "EngineVersion": c.get("engine_version", ""),
                    "CacheNodeType": c["node_type"],
                    "NumCacheNodes": c.get("num_nodes", 1),
                    "CacheSubnetGroupName": c.get("subnet_group", ""),
                    "VpcSecurityGroupIds": c.get("security_groups", []),
                },
            }
        return result

    def _efs_file_systems(self) -> dict:
        result = {}
        for fs in self.resources.get("efs_file_systems", []):
            lid = self._lid(fs["id"], "EFS")
            props = {
                "PerformanceMode": fs.get("performance_mode", "generalPurpose"),
                "ThroughputMode": fs.get("throughput_mode", "bursting"),
                "Encrypted": fs.get("encrypted", False),
            }
            if fs.get("kms_key_id"):
                props["KmsKeyId"] = fs["kms_key_id"]
            result[lid] = {"Type": "AWS::EFS::FileSystem", "Properties": props}
        return result

    # ── App, API & messaging ──────────────────────────────────────────────────

    def _rest_apis(self) -> dict:
        result = {}
        for api in self.resources.get("rest_apis", []):
            lid = self._lid(api["name"], "RestAPI")
            result[lid] = {
                "Type": "AWS::ApiGateway::RestApi",
                "Properties": {
                    "Name": api["name"],
                    "Description": api.get("description", ""),
                    "EndpointConfiguration": {"Types": [api.get("endpoint_type", "REGIONAL")]},
                    "Tags": tags_to_cfn(api.get("tags", {})),
                },
            }
        return result

    def _http_apis(self) -> dict:
        result = {}
        for api in self.resources.get("http_apis", []):
            lid = self._lid(api["name"], "HttpAPI")
            props = {"Name": api["name"], "ProtocolType": api.get("protocol_type", "HTTP")}
            cors = api.get("cors_configuration", {})
            if cors:
                props["CorsConfiguration"] = {
                    "AllowOrigins": cors.get("AllowOrigins", ["*"]),
                    "AllowMethods": cors.get("AllowMethods", ["*"]),
                }
            result[lid] = {"Type": "AWS::ApiGatewayV2::Api", "Properties": props}
        return result

    def _cloudfront_distributions(self) -> dict:
        result = {}
        for d in self.resources.get("cloudfront_distributions", []):
            lid = self._lid(d["id"], "CF")
            origins = [{"Id": o["id"], "DomainName": o["domain"], "S3OriginConfig": {"OriginAccessIdentity": ""}} for o in d.get("origins", [])]
            result[lid] = {
                "Type": "AWS::CloudFront::Distribution",
                "Properties": {
                    "DistributionConfig": {
                        "Enabled": d.get("enabled", True),
                        "DefaultRootObject": d.get("default_root_object", ""),
                        "PriceClass": d.get("price_class", "PriceClass_All"),
                        "Origins": origins,
                        "DefaultCacheBehavior": {
                            "TargetOriginId": origins[0]["Id"] if origins else "",
                            "ViewerProtocolPolicy": d.get("viewer_protocol_policy", "redirect-to-https"),
                            "ForwardedValues": {"QueryString": False, "Cookies": {"Forward": "none"}},
                        },
                        "ViewerCertificate": {"CloudFrontDefaultCertificate": True},
                        "Restrictions": {"GeoRestriction": {"RestrictionType": "none", "Locations": []}},
                    }
                },
            }
        return result

    def _route53_zones(self) -> dict:
        return {
            self._lid(z["name"], "Zone"): {
                "Type": "AWS::Route53::HostedZone",
                "Properties": {
                    "Name": z["name"],
                    "HostedZoneConfig": {"Comment": z.get("comment", "")},
                },
            }
            for z in self.resources.get("route53_zones", [])
        }

    def _acm_certificates(self) -> dict:
        result = {}
        for cert in self.resources.get("acm_certificates", []):
            lid = self._lid(cert["domain"], "Cert")
            props = {
                "DomainName": cert["domain"],
                "ValidationMethod": cert.get("validation_method", "DNS"),
            }
            san = [s for s in cert.get("san", []) if s != cert["domain"]]
            if san:
                props["SubjectAlternativeNames"] = san
            result[lid] = {"Type": "AWS::CertificateManager::Certificate", "Properties": props}
        return result

    def _sns_topics(self) -> dict:
        result = {}
        for t in self.resources.get("sns_topics", []):
            lid = self._lid(t["name"], "SNS")
            props = {"TopicName": t["name"]}
            if t.get("display_name"):
                props["DisplayName"] = t["display_name"]
            if t.get("kms_key_id"):
                props["KmsMasterKeyId"] = t["kms_key_id"]
            if t.get("fifo"):
                props["FifoTopic"] = True
            result[lid] = {"Type": "AWS::SNS::Topic", "Properties": props}
        return result

    def _sqs_queues(self) -> dict:
        result = {}
        for q in self.resources.get("sqs_queues", []):
            lid = self._lid(q["name"], "SQS")
            props = {
                "QueueName": q["name"],
                "VisibilityTimeout": q.get("visibility_timeout", 30),
                "MessageRetentionPeriod": q.get("message_retention", 345600),
                "DelaySeconds": q.get("delay_seconds", 0),
                "MaximumMessageSize": q.get("max_message_size", 262144),
            }
            if q.get("kms_key_id"):
                props["KmsMasterKeyId"] = q["kms_key_id"]
            if q.get("fifo"):
                props["FifoQueue"] = True
            result[lid] = {"Type": "AWS::SQS::Queue", "Properties": props}
        return result

    def _kinesis_streams(self) -> dict:
        result = {}
        for s in self.resources.get("kinesis_streams", []):
            lid = self._lid(s["name"], "Kinesis")
            props = {
                "Name": s["name"],
                "ShardCount": s.get("shard_count", 1),
                "RetentionPeriodHours": s.get("retention_period", 24),
            }
            if s.get("encryption_type") == "KMS" and s.get("key_id"):
                props["StreamEncryption"] = {"EncryptionType": "KMS", "KeyId": s["key_id"]}
            result[lid] = {"Type": "AWS::Kinesis::Stream", "Properties": props}
        return result

    def _eventbridge_rules(self) -> dict:
        result = {}
        for r in self.resources.get("eventbridge_rules", []):
            lid = self._lid(r["name"], "EBRule")
            props = {"Name": r["name"], "State": r.get("state", "ENABLED")}
            if r.get("schedule"):
                props["ScheduleExpression"] = r["schedule"]
            if r.get("event_pattern"):
                props["EventPattern"] = r["event_pattern"]
            if r.get("description"):
                props["Description"] = r["description"]
            result[lid] = {"Type": "AWS::Events::Rule", "Properties": props}
        return result

    # ── Security, monitoring & DevOps ─────────────────────────────────────────

    def _secrets(self) -> dict:
        result = {}
        for s in self.resources.get("secrets", []):
            lid = self._lid(s["name"], "Secret")
            props = {"Name": s["name"]}
            if s.get("description"):
                props["Description"] = s["description"]
            if s.get("kms_key_id"):
                props["KmsKeyId"] = s["kms_key_id"]
            result[lid] = {"Type": "AWS::SecretsManager::Secret", "Properties": props}
        return result

    def _kms_keys(self) -> dict:
        result = {}
        for k in self.resources.get("kms_keys", []):
            lid = self._lid(k["id"], "KMS")
            result[lid] = {
                "Type": "AWS::KMS::Key",
                "Properties": {
                    "Description": k.get("description", ""),
                    "EnableKeyRotation": True,
                    "PendingWindowInDays": k.get("deletion_window", 30),
                    "MultiRegion": k.get("multi_region", False),
                    "KeyPolicy": {
                        "Version": "2012-10-17",
                        "Statement": [{"Effect": "Allow", "Principal": {"AWS": {"Fn::Sub": "arn:aws:iam::${AWS::AccountId}:root"}}, "Action": "kms:*", "Resource": "*"}],
                    },
                },
            }
            result[f"{lid}Alias"] = {
                "Type": "AWS::KMS::Alias",
                "Properties": {"AliasName": f"alias/{slugify(k['id'])}", "TargetKeyId": {"Ref": lid}},
            }
        return result

    def _cloudwatch_alarms(self) -> dict:
        result = {}
        for a in self.resources.get("cloudwatch_alarms", []):
            lid = self._lid(a["name"], "Alarm")
            props = {
                "AlarmName": a["name"],
                "MetricName": a.get("metric_name", ""),
                "Namespace": a.get("namespace", ""),
                "Statistic": a.get("statistic", "Average"),
                "Period": a.get("period", 300),
                "EvaluationPeriods": a.get("evaluation_periods", 1),
                "Threshold": a.get("threshold", 0),
                "ComparisonOperator": a.get("comparison_operator", "GreaterThanThreshold"),
            }
            if a.get("alarm_actions"):
                props["AlarmActions"] = a["alarm_actions"]
            if a.get("dimensions"):
                props["Dimensions"] = [{"Name": k, "Value": v} for k, v in a["dimensions"].items()]
            result[lid] = {"Type": "AWS::CloudWatch::Alarm", "Properties": props}
        return result

    def _log_groups(self) -> dict:
        result = {}
        for g in self.resources.get("cloudwatch_log_groups", []):
            lid = self._lid(g["name"], "LogGroup")
            props = {"LogGroupName": g["name"]}
            if g.get("retention_days"):
                props["RetentionInDays"] = g["retention_days"]
            if g.get("kms_key_id"):
                props["KmsKeyId"] = g["kms_key_id"]
            result[lid] = {"Type": "AWS::Logs::LogGroup", "Properties": props}
        return result

    def _codepipelines(self) -> dict:
        result = {}
        for p in self.resources.get("codepipelines", []):
            lid = self._lid(p["name"], "Pipeline")
            store = p.get("artifact_store", {})
            result[lid] = {
                "Type": "AWS::CodePipeline::Pipeline",
                "Properties": {
                    "Name": p["name"],
                    "RoleArn": p.get("role_arn", ""),
                    "ArtifactStore": {"Type": store.get("Type", "S3"), "Location": store.get("Location", "")},
                    "Stages": [],
                },
            }
        return result

    def _codebuild_projects(self) -> dict:
        result = {}
        for proj in self.resources.get("codebuild_projects", []):
            lid = self._lid(proj["name"], "Build")
            result[lid] = {
                "Type": "AWS::CodeBuild::Project",
                "Properties": {
                    "Name": proj["name"],
                    "Description": proj.get("description", ""),
                    "ServiceRole": proj.get("service_role", ""),
                    "TimeoutInMinutes": proj.get("build_timeout", 60),
                    "Artifacts": {"Type": proj.get("artifacts_type", "NO_ARTIFACTS")},
                    "Environment": {
                        "ComputeType": proj.get("compute_type", "BUILD_GENERAL1_SMALL"),
                        "Image": proj.get("image", "aws/codebuild/standard:7.0"),
                        "Type": proj.get("environment_type", "LINUX_CONTAINER"),
                    },
                    "Source": {"Type": proj.get("source_type", "NO_SOURCE")},
                },
            }
        return result

    def _waf_acls(self) -> dict:
        result = {}
        for acl in self.resources.get("waf_web_acls", []):
            lid = self._lid(acl["name"], "WAF")
            result[lid] = {
                "Type": "AWS::WAFv2::WebACL",
                "Properties": {
                    "Name": acl["name"],
                    "Description": acl.get("description", ""),
                    "Scope": acl.get("scope", "REGIONAL"),
                    "DefaultAction": {"Allow": {}},
                    "VisibilityConfig": {
                        "CloudWatchMetricsEnabled": True,
                        "MetricName": slugify(acl["name"]),
                        "SampledRequestsEnabled": True,
                    },
                    "Rules": [],
                },
            }
        return result

    def _load_balancers(self) -> dict:
        result = {}
        for lb in self.resources.get("load_balancers", []):
            lid = self._lid(lb["name"], "ALB")
            result[lid] = {
                "Type": "AWS::ElasticLoadBalancingV2::LoadBalancer",
                "Properties": {
                    "Name": lb["name"], "Type": lb["type"],
                    "Scheme": lb.get("scheme", "internet-facing"),
                    "Subnets": lb.get("subnets", []),
                    "SecurityGroups": lb.get("security_groups", []),
                },
            }
        return result

    def _iam_roles(self) -> dict:
        result = {}
        for role in self.resources.get("iam_roles", []):
            lid = self._lid(role["name"], "Role")
            result[lid] = {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "RoleName": role["name"], "Path": role["path"],
                    "AssumeRolePolicyDocument": role["assume_role_policy"],
                    "ManagedPolicyArns": role.get("attached_policies", []),
                },
            }
        return result

    def _outputs(self, resources: dict) -> dict:
        output_types = {
            "AWS::EC2::VPC", "AWS::S3::Bucket", "AWS::RDS::DBInstance",
            "AWS::ElasticLoadBalancingV2::LoadBalancer", "AWS::EKS::Cluster",
            "AWS::ECR::Repository", "AWS::DynamoDB::Table",
            "AWS::ApiGateway::RestApi", "AWS::ApiGatewayV2::Api",
            "AWS::CloudFront::Distribution", "AWS::KMS::Key",
        }
        return {
            f"{lid}Id": {
                "Description": f"{lid} resource ID",
                "Value": {"Ref": lid},
                "Export": {"Name": {"Fn::Sub": f"${{AWS::StackName}}-{lid}"}},
            }
            for lid, resource in resources.items()
            if resource.get("Type") in output_types
        }
