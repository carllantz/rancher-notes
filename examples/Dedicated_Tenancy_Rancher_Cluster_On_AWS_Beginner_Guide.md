## Dedicated Tenancy Rancher Cluster on AWS: A Beginner's Guide

A step-by-step beginner's guide to building a Rancher RKE2 cluster on AWS where every server is an EC2 Dedicated Instance, using an existing Rancher management cluster, existing IAM resources and an existing VPC.

## Task

**Dedicated tenancy** is an AWS setting that runs your EC2 instances (virtual servers you rent from AWS) on hardware that is dedicated to your AWS account alone. This guide shows you how to build a Kubernetes cluster where every server is a Dedicated Instance, managed by **Rancher**. Rancher's usual EC2 tool, the amazonec2 node driver, cannot ask AWS for dedicated hardware. So this guide uses **CAPA** (Cluster API Provider for AWS), a tool that Rancher can use instead. You start from things that already exist: a Rancher management cluster, IAM instance profiles, an IAM access key, and a VPC (your private network in AWS) with its subnets. You add CAPA to Rancher, give Rancher the access key, and describe the new cluster in a Helm chart (a small package of templates plus a settings file). One command then builds the cluster inside your VPC.

At the end, your existing Rancher manages a new three-server RKE2 v1.35.9+rke2r1 cluster that shows **Active** in Rancher. All three servers (the control-plane pool `cp` and the worker pools `wd` and `ws`) run as EC2 Dedicated Instances in your own subnets, and you have checked this in AWS. You have also run a small web app on the cluster. Finally, you delete the cluster with one command, confirm that its instances are terminated and that your VPC is still there, and remove the tags CAPA added to your subnets.

The diagram shows the big picture: what already exists, and what CAPA creates.

![Big picture: your workstation runs AWS CLI checks against AWS us-east-1 and uses kubectl, helm and the existing access key against your existing Rancher management cluster (RKE2 v1.36.4+rke2r1), which runs Rancher 2.15.2 (Carbide) and Rancher Turtles 0.27.2, with CAPA v2.11.1 added in Step 1; in AWS, the IAM instance profiles, the access key and your VPC with its existing public or private subnets already exist; CAPA creates the security groups, the internal NLB and three EC2 Dedicated Instances cp m5.large, wd m5.large and ws t3.medium in your existing subnets; Rancher bootstraps RKE2 on them, and the nodes reach Rancher on TCP 443 over the subnets' internet route](assets/dedicated-tenancy-beginner-02-big-picture.png)

Think of tenancy like housing. Shared tenancy is an apartment building: you have your own flat, but your neighbours share the building. Dedicated tenancy is a house that only you live in, but you still rent it, and AWS still owns and runs it.

![Shared tenancy versus Dedicated Instances: on the left, tenancy default is like an apartment building, with your EC2 instance on one physical AWS server next to instances of Customer B and Customer C; on the right, tenancy dedicated is like a house only you live in but still rent from AWS, with two of your EC2 instances on a physical AWS server used by your account only; in a VPC with default tenancy, tenancy is set on each EC2 instance, and this guide sets tenancy dedicated for the pools cp, wd and ws](assets/dedicated-tenancy-beginner-01-shared-vs-dedicated.png)

## Pre-requisites

Before you begin, make sure you have the following:

1. **A workstation with the AWS CLI:** Your workstation (your own computer) has the AWS CLI installed, with credentials that can read EC2 instances, VPCs and subnets in the region, and delete subnet tags (Step 8.4).

2. **An existing Rancher management cluster:** Rancher 2.15.2 running on a management cluster, reachable at `RANCHER_HOSTNAME`. Rancher 2.15.2 installs Rancher Turtles 0.27.2 and Cluster API core by itself, a few minutes after the first login, so you do not install them. Rancher must accept TCP 443 from `0.0.0.0/0`, because the new cluster reaches Rancher from addresses you do not control. If you do not have a management cluster yet, build one with Steps 1 to 4 of [Rancher Turtles and Cluster API](../infra/Rancher_Turtles_Cluster_API.md).

3. **Admin access to the management cluster:** An admin host (the machine where you run `kubectl` and `helm` v3.22.0) with a kubeconfig that has admin rights on the management cluster. The admin host can be your workstation. The management cluster needs no AWS credentials of its own.

4. **A Rancher API token:** An API token for an administrator, created in the Rancher UI under **Account & API Keys**. Step 2.1 uses it to create the cloud credential.

5. **Existing IAM instance profiles:** Two IAM instance profiles that give the servers their AWS permissions: one for the control plane (`CONTROL_PLANE_INSTANCE_PROFILE`) and one for the other nodes (`NODES_INSTANCE_PROFILE`). Step 5 of [Rancher Turtles and Cluster API](../infra/Rancher_Turtles_Cluster_API.md) shows how `clusterawsadm` creates them as `control-plane.<name>` and `nodes.<name>`.

6. **An existing IAM access key:** The access key ID and secret access key of the IAM user that CAPA works as, with the permissions CAPA needs. Step 5 of [Rancher Turtles and Cluster API](../infra/Rancher_Turtles_Cluster_API.md) creates this user (the `clusterawsadm` bootstrap user) and its access key. If Rancher already holds an AWS cloud credential for this key, Step 2 shows where to pick up.

7. **An existing VPC and two subnets:** A VPC (`VPC_ID`) and two subnets in it for the nodes (`SUBNET_ID_1` and `SUBNET_ID_2`). Step 3.2 collects each subnet's IPv4 CIDR block. The nodes need outbound internet access, to reach Rancher on TCP 443 and to pull public images. Either of these layouts works:
   - **Private subnets:** subnets with no route to an internet gateway, each with a NAT gateway and Elastic IP address. Each NAT gateway sits in a public subnet in the same availability zone, the public subnets have an internet gateway, and route table associations send each private subnet's internet traffic through its NAT gateway.
   - **Public subnets:** subnets whose route table sends `0.0.0.0/0` to an internet gateway, and that auto-assign public IPv4 addresses. The nodes then get public IP addresses.

   You do not need to tag the subnets. CAPA adds `kubernetes.io/cluster/CLUSTER_NAME` = `shared`, `kubernetes.io/role/internal-elb` = `1` and your `Project` tag to the subnets you list, and leaves them there when the cluster is deleted. Step 8.4 removes them.

8. **An EC2 key pair and an AMI ID:** An EC2 key pair in the region (`SSH_KEY_NAME`) and the ID of the Canonical Ubuntu 24.04 LTS AMI (`AMI_ID`). Canonical publishes the current ID in the SSM parameter `/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id`.

## Environment

The steps in this article were tested end to end on 2026-10-14 in AWS region `us-east-1`, in the account's default VPC. The private-subnet layout in the prerequisites comes from the CAPA documentation; the test run used the public-subnet layout.

The existing management cluster was:

- **Rancher:** Rancher Government Carbide 2.15.2, chart `oci://registry.ranchercarbide.dev/carbide-charts/rancher` 2.15.2, rancher-webhook 110.0.3+up0.11.3
- **Management cluster:** RKE2 v1.36.4+rke2r1, single node, c5.2xlarge, Ubuntu 26.04 LTS, kernel 7.0.0-1014-aws
- **cert-manager:** v1.21.1
- **Rancher Turtles:** 0.27.2, chart `rancher-turtles-110.0.2+up0.27.2`, installed by Rancher. Its `rancher-credential-translation` feature is on by default.
- **Cluster API core:** v1.13.3

The existing AWS network was:

- **VPC:** default tenancy, `172.31.0.0/16`. It also contains an IPv6-only subnet.
- **Subnets used:** two public subnets, in `us-east-1a` (`172.31.16.0/20`) and `us-east-1b` (`172.31.32.0/20`), with a `0.0.0.0/0` route to an internet gateway through the VPC's main route table, and auto-assign public IPv4 addresses on

The tools used, and the components this guide adds or creates, were:

- **Helm:** v3.22.0
- **AWS CLI:** 2.37.6 on the workstation
- **CAPA:** v2.11.1, Rancher's build from `rancher/cluster-api-provider-aws` (image `registry.ranchercarbide.dev/rancher/cluster-api-aws-controller:v2.11.1`), deliberately pinned in the `CAPIProvider` `aws`
- **Downstream RKE2:** v1.35.9+rke2r1 (containerd 2.2.7-k3s1), Ubuntu 24.04.5 LTS, AMI `ami-0fa5967347d08d2df` (stock Canonical image)
- **Machine types and tenancy:** m5.large for the `cp` and `wd` pools, t3.medium for the `ws` pool, all three with tenancy `dedicated`
- **AWS cloud controller manager:** chart `aws-cloud-controller-manager` 0.0.12 (appVersion v1.35.0), deliberately pinned
- **CNI:** RKE2-bundled Calico
- **Test workload:** `nginx:1.27.5-alpine`, `busybox:1.37.0`

## Procedure

### Variables Used in This Part

Every `UPPER_CASE` word in a command is a placeholder. Replace it with your own value, using find-and-replace, before you run the command.

| Placeholder | Meaning | Example value |
|---|---|---|
| `RANCHER_HOSTNAME` | DNS name of the Rancher server | `rancher-capadt.example.com` |
| `CAPA_REGION` | AWS region of the credential, the VPC and the new cluster | `us-east-1` |
| `ACCESS_KEY_ID` | Access key ID of your existing IAM access key | `AKIAXXXXXXXXXXXXXXXX` |
| `SECRET_ACCESS_KEY` | Secret access key of your existing IAM access key | the secret you saved when the key was created |
| `CONTROL_PLANE_INSTANCE_PROFILE` | Existing IAM instance profile for the control-plane server | `control-plane.kbtest-capabyo` |
| `NODES_INSTANCE_PROFILE` | Existing IAM instance profile for the worker servers | `nodes.kbtest-capabyo` |
| `VPC_ID` | ID of your existing VPC | `vpc-03d91b25c85f6c6a6` |
| `SUBNET_ID_1` | ID of the first existing subnet for the nodes | `subnet-06e163a2140f18e22` |
| `SUBNET_CIDR_1` | IPv4 CIDR block of `SUBNET_ID_1` | `172.31.16.0/20` |
| `SUBNET_ID_2` | ID of the second existing subnet for the nodes | `subnet-019f175fb25765528` |
| `SUBNET_CIDR_2` | IPv4 CIDR block of `SUBNET_ID_2` | `172.31.32.0/20` |
| `PROJECT_TAG` | Value of the `Project` tag that CAPA puts on every AWS resource it creates and on your subnets | `kbtest-capabyo` |
| `CLUSTER_NAME` | Name of the new cluster. It starts every machine and template name | `capadt` |
| `KUBERNETES_VERSION` | RKE2 version of the new cluster | `v1.35.9+rke2r1` |
| `SSH_KEY_NAME` | EC2 key pair name for the new cluster's servers | `kbtest-capabyo-key` |
| `AMI_ID` | Ubuntu 24.04 LTS AMI ID in `CAPA_REGION` | `ami-0fa5967347d08d2df` |
| `CREDENTIAL_DISPLAY_NAME` | Display name of the Rancher AWS cloud credential | `capa-dedicated-aws` |
| `CREDENTIAL_SECRET_ID` | Secret name of the cloud credential (the part after `cattle-global-data:`). Turtles uses it as the identity name | `cc-a1b2c` |
| `RANCHER_TOKEN` | Rancher API token from the prerequisites | `token-abcde:xxxxxxxxxxxxxxxx` |
| `MGMT_CLUSTER_ID` | Rancher's ID for the new cluster, shown in the CLUSTER NAME column in Step 5.3 | `c-m-nvfbpsr6` |
| `INSTANCE_IDS` | The cluster's EC2 instance IDs, separated by spaces, from the NODE NAME column in Step 6.3 (Step 9.6 only) | `i-0c758b7c808d024ef i-0356b0c4190dd2fa6 i-045b4e7c6d9c44ce0` |

> **Note:** The expected output uses the example values in this table and the cluster name `capadt`. Your IDs, IP addresses and the 8-character endings of the template names differ. Those endings are a hash of the AMI ID, the key pair name, and each pool's instance type, instance profile and tenancy.

### Your Roadmap

The guide has 9 steps. Each step starts with a "You are here" line that says where to run its commands. Most commands run on the admin host. The AWS commands run on your workstation, because that is where your AWS credentials are.

![Roadmap of 9 steps in two columns: Connect Rancher to AWS (Step 1 Confirm Turtles and Install the CAPA Provider, Step 2 Create the AWS Cloud Credential, Step 3 Check the Existing VPC on the workstation), Build the dedicated cluster (Step 4 Write the Cluster Template Chart, Step 5 Install the Cluster Template, Step 6 Wait for the Cluster to Become Active, Step 7 Check That Every Node Is Dedicated), and Clean up and fix problems (Step 8 Delete the Cluster, Step 9 Troubleshoot Common Problems), each labelled with where it runs](assets/dedicated-tenancy-beginner-03-roadmap.png)

---

### Step 1 — Confirm Turtles and Install the CAPA Provider

*You are here: Step 1 of 9. Run on: the admin host.*

First you check that Rancher has installed Turtles and Cluster API core on your management cluster. Then you find the CAPA version your Rancher ships, and ask Turtles to install CAPA, the part that creates AWS resources, pinned to that version with a `CAPIProvider` object.

#### 1.1 Check Turtles and Cluster API Core

Rancher installs Turtles a few minutes after the first login in the Rancher UI.

**What this does:** Lists the Helm releases in the Turtles namespace.

```bash
helm list -n cattle-turtles-system
```

Expected output (your `REVISION` and `UPDATED` values differ):
```
NAME           	NAMESPACE            	REVISION	UPDATED                                	STATUS  	CHART                           	APP VERSION
rancher-turtles	cattle-turtles-system	7       	2026-10-01 14:53:57.905651954 +0000 UTC	deployed	rancher-turtles-110.0.2+up0.27.2	0.27.2     
```

**What this does:** Lists the Cluster API providers that Turtles manages.

```bash
kubectl get capiproviders -A
```

Expected output before you add CAPA lists only the core provider:
```
NAMESPACE            NAME          TYPE   PROVIDERNAME   INSTALLEDVERSION   PHASE
cattle-capi-system   cluster-api   core   cluster-api    v1.13.3            Ready
```

> **Note:** The `capiproviders` resource type does not exist until Turtles is installed. If the command returns `the server doesn't have a resource type "capiproviders"`, see Step 9.1.

#### 1.2 Find the CAPA Version Your Rancher Ships

Turtles keeps the download address of each provider release in the ConfigMap `clusterctl-config`.

**What this does:** Prints the line of that ConfigMap that names the AWS provider release.

```bash
kubectl -n cattle-turtles-system get configmap clusterctl-config -o jsonpath='{.data.clusterctl\.yaml}' | grep cluster-api-provider-aws
```

Expected output on Rancher Government Carbide 2.15.2:
```
  url: https://github.com/rancher/cluster-api-provider-aws/releases/v2.11.1/infrastructure-components.yaml
```

The version in the address (here `v2.11.1`) is the CAPA version to put in the manifest in Step 1.3.

> **Note:** If the `CAPIProvider` asks for a different version, Turtles installs the version listed in `clusterctl-config` anyway and rewrites the provider's `spec.version` to match. Use the listed version so that the manifest and the cluster agree.

#### 1.3 Write the Provider Manifest

**What this does:** Writes a file that describes the `capa-system` namespace and the CAPA provider.

```bash
cat > capa-provider.yaml <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: capa-system
---
apiVersion: turtles-capi.cattle.io/v1alpha1
kind: CAPIProvider
metadata:
  name: aws
  namespace: capa-system
spec:
  type: infrastructure
  version: v2.11.1                 # CAPA release that Rancher 2.15.2 Carbide ships (Step 1.2)
  enableAutomaticUpdate: false     # Turtles does not move CAPA to a newer release on its own
  variables:
    AWS_B64ENCODED_CREDENTIALS: "" # left empty; clusters authenticate with AWSClusterStaticIdentity objects
EOF
```

#### 1.4 Apply the Provider

**What this does:** Sends the file to the management cluster, which creates the namespace and the provider.

```bash
kubectl apply -f capa-provider.yaml
```

Expected output:
```
namespace/capa-system created
capiprovider.turtles-capi.cattle.io/aws created
```

#### 1.5 Confirm the Provider Is Ready

The provider reaches `Ready` within about 30 seconds.

**What this does:** Lists the Cluster API providers again. CAPA now appears next to the core provider.

```bash
kubectl get capiproviders -A
```

Expected output:
```
NAMESPACE            NAME          TYPE             PROVIDERNAME   INSTALLEDVERSION   PHASE
capa-system          aws           infrastructure   aws            v2.11.1            Ready
cattle-capi-system   cluster-api   core             cluster-api    v1.13.3            Ready
```

#### 1.6 Confirm CAPA Knows About Tenancy

**What this does:** Asks Kubernetes to describe the `tenancy` field of CAPA's machine template. This proves that CAPA can ask AWS for dedicated hardware.

```bash
kubectl explain awsmachinetemplate.spec.template.spec.tenancy
```

Expected output begins with `FIELD: tenancy <string>` and lists the allowed values `default`, `dedicated` and `host`.

> **Note:** Rancher's amazonec2 node driver, the usual way Rancher creates EC2 servers, has no tenancy field. Machine pools that use it cannot ask for Dedicated Instances. That is why this guide uses CAPA, which sets `tenancy` on each AWSMachineTemplate.

#### 1.7 Verification Checklist

- [ ] Turtles deployed: `helm list -n cattle-turtles-system` shows `rancher-turtles` with `STATUS deployed` and `APP VERSION 0.27.2`
- [ ] CAPA version found: the command in Step 1.2 prints a `url:` line with the CAPA version
- [ ] Provider created: `kubectl get capiproviders -n capa-system aws` returns one row
- [ ] Provider ready at the pinned version: `kubectl get capiproviders -A` shows `aws` with `INSTALLEDVERSION v2.11.1` and `PHASE Ready`
- [ ] Tenancy in the schema: `kubectl explain awsmachinetemplate.spec.template.spec.tenancy` prints `FIELD: tenancy <string>`

---

### Step 2 — Create the AWS Cloud Credential

*You are here: Step 2 of 9. Run on: the admin host.*

Rancher stores your existing access key as a cloud credential. Turtles then copies it into an `AWSClusterStaticIdentity`, the form that CAPA uses. Turtles does this only when the credential's Secret carries the annotation (a label-like note) `provisioning.cattle.io/driver: aws`. The steps below add it if it is missing.

If Rancher already holds an AWS cloud credential for this access key, skip Step 2.1, use that credential's Secret name as `CREDENTIAL_SECRET_ID`, and start at Step 2.2. The annotation and identity checks are still required.

![Credential to identity: your existing access key (access key ID and secret access key) is sent to Rancher 2.15.2 with curl POST /v3/cloudcredentials in Step 2.1; Rancher stores the cloud credential Secret cc-a1b2c in cattle-global-data, which needs the annotation provisioning.cattle.io/driver = aws; when the annotation is present, Rancher Turtles 0.27.2 rancher-credential-translation creates the AWSClusterStaticIdentity cc-a1b2c with allowedNamespaces fleet-default and secretRef cc-a1b2c, which points to a copy of the keys in Secret cc-a1b2c in capa-system; the AWSCluster capadt in fleet-default points to the identity with identityRef, and CAPA uses this identity to create the AWS resources](assets/dedicated-tenancy-beginner-04-credential-to-identity.png)

#### 2.1 Create the Cloud Credential through the Rancher API

Use the Rancher API token from the prerequisites as `RANCHER_TOKEN`.

Turn off shell history for this session, so the secret key in the next command is not saved to your history file:

```bash
set +o history
```

Expected output: none.

**What this does:** Asks the Rancher API to create a cloud credential from your existing access key.

```bash
curl -s -X POST "https://RANCHER_HOSTNAME/v3/cloudcredentials" \
  -H "Authorization: Bearer RANCHER_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"cloudCredential\",\"name\":\"CREDENTIAL_DISPLAY_NAME\",\"amazonec2credentialConfig\":{\"accessKey\":\"ACCESS_KEY_ID\",\"secretKey\":\"SECRET_ACCESS_KEY\",\"defaultRegion\":\"CAPA_REGION\"}}"
```

Expected output is the JSON description of the new credential. Its `id` field looks like `cattle-global-data:CREDENTIAL_SECRET_ID`. The part after the colon is the Secret name, `CREDENTIAL_SECRET_ID`. Write it down.

Turn shell history back on:

```bash
set -o history
```

Expected output: none.

> **Note:** The `-d` argument puts the secret key on the command line while the request runs, so other local users can see it in a process listing. Turning off shell history keeps it out of your history file, but not out of the process listing.

> **Note:** You can also create the credential on the **Cloud Credentials** page of the Rancher UI, with the same access key ID and secret access key. Either way, check the result in Step 2.2.

> **STIG:** CAPA works in AWS with a long-lived IAM access key. Rancher stores a copy of the key in a Secret in `cattle-global-data`, and Turtles copies it again into a Secret in `capa-system`. The tradeoff is that the key does not expire on its own, and anyone who can read those Secrets holds the key. Limit who can read the `cattle-global-data` and `capa-system` Secrets.

#### 2.2 Check Whether Turtles Created the Identity

Wait about 30 seconds.

**What this does:** Lists the CAPA identities.

```bash
kubectl get awsclusterstaticidentities
```

If the output lists `CREDENTIAL_SECRET_ID`, skip Step 2.3 and go to Step 2.4. If the output is `No resources found`, the Secret is missing the annotation. Check its annotations:

**What this does:** Prints the annotations on the credential's Secret.

```bash
kubectl -n cattle-global-data get secret CREDENTIAL_SECRET_ID -o jsonpath='{.metadata.annotations}'
```

Expected output lists only Rancher's own annotations, with no `provisioning.cattle.io/driver` key:
```
{"field.cattle.io/creatorId":"user-xxxxx","field.cattle.io/name":"CREDENTIAL_DISPLAY_NAME"}
```

#### 2.3 Add the Driver Annotation to the Credential Secret

**What this does:** Adds the annotation that tells Turtles this Secret holds AWS keys.

```bash
kubectl -n cattle-global-data annotate secret CREDENTIAL_SECRET_ID provisioning.cattle.io/driver=aws
```

Expected output:
```
secret/cc-a1b2c annotated
```

> **Note:** Turtles only watches Secrets in `cattle-global-data` that carry this annotation, and only when the `aws` CAPIProvider from Step 1 is `Ready`. The identity takes the Secret's name (`cc-xxxxx`), not the credential's display name.

#### 2.4 Confirm the Identity Was Created

Wait about 10 seconds.

**What this does:** Lists the CAPA identities again.

```bash
kubectl get awsclusterstaticidentities
```

Expected output lists your identity. It can also list identities made from other annotated AWS cloud credentials, so look for the row named `CREDENTIAL_SECRET_ID`:
```
NAME       AGE
cc-a1b2c   30m
cc-r5b2f   30m
```

**What this does:** Shows which namespaces may use the identity and which Secret holds its keys.

```bash
kubectl get awsclusterstaticidentity CREDENTIAL_SECRET_ID -o jsonpath='{.spec}'
```

Expected output:
```
{"allowedNamespaces":{"list":["fleet-default"],"selector":{}},"secretRef":"cc-a1b2c"}
```

**What this does:** Shows the copy of the keys that Turtles wrote to `capa-system`.

```bash
kubectl -n capa-system get secret CREDENTIAL_SECRET_ID
```

Expected output shows the Secret with type `Opaque` and two data keys, `AccessKeyID` and `SecretAccessKey`.

> **Note:** The identity's `allowedNamespaces` is fixed to `fleet-default`. Only clusters described in that namespace can use it. The chart in Step 4 creates its objects in `fleet-default`.

> **STIG:** The identity lets any AWSCluster in `fleet-default` that refers to it create resources in your AWS account. Limit who can create or edit clusters in that namespace and who can read the cloud credential.

#### 2.5 Verification Checklist

- [ ] Credential exists: `kubectl -n cattle-global-data get secret CREDENTIAL_SECRET_ID` returns the Secret
- [ ] Driver annotation present: `kubectl -n cattle-global-data get secret CREDENTIAL_SECRET_ID -o jsonpath='{.metadata.annotations.provisioning\.cattle\.io/driver}'` prints `aws`
- [ ] Identity created: `kubectl get awsclusterstaticidentities` lists `CREDENTIAL_SECRET_ID`
- [ ] Identity limited to fleet-default: `kubectl get awsclusterstaticidentity CREDENTIAL_SECRET_ID -o jsonpath='{.spec.allowedNamespaces}'` prints `{"list":["fleet-default"]}`

---

### Step 3 — Check the Existing VPC

*You are here: Step 3 of 9. Run on: your workstation.*

CAPA will put the new servers into your existing VPC and subnets. It will not create a VPC, subnets, NAT gateways or route tables. It still creates the security groups and the control-plane load balancer. Before you install anything, check the VPC's tenancy and collect the details of your two subnets.

#### 3.1 Check the VPC Tenancy

**What this does:** Shows your VPC's ID, its instance tenancy setting and its address range.

```bash
aws ec2 describe-vpcs --vpc-ids VPC_ID --query 'Vpcs[].[VpcId,InstanceTenancy,CidrBlock]' --output table
```

Expected output is one row with your VPC ID, its tenancy (`default` or `dedicated`) and its CIDR block:
```
-------------------------------------------------------
|                    DescribeVpcs                     |
+------------------------+----------+-----------------+
|  vpc-03d91b25c85f6c6a6 |  default |  172.31.0.0/16  |
+------------------------+----------+-----------------+
```

> **Note:** AWS gives a VPC one of two tenancy values. In a VPC with tenancy `dedicated`, every instance runs as a Dedicated Instance. In a VPC with tenancy `default`, instances get `default` tenancy unless the launch asks for `dedicated`. A `default` VPC is the usual case, and there the `tenancy: dedicated` setting in the chart (Step 4.2) is what makes each server dedicated. The chart sets it on every pool either way.

#### 3.2 Collect the Subnet IDs and CIDR Blocks

**What this does:** Shows each subnet's ID, availability zone, IPv4 CIDR block, and whether it gives new instances a public IPv4 address.

```bash
aws ec2 describe-subnets --subnet-ids SUBNET_ID_1 SUBNET_ID_2 --query 'Subnets[].[SubnetId,AvailabilityZone,CidrBlock,MapPublicIpOnLaunch]' --output table
```

Expected output is a table with one row per subnet: its ID, its zone (such as `us-east-1a`), its IPv4 CIDR block (such as `172.31.16.0/20`), and `True` or `False` for automatic public IPv4 addresses. Use the CIDR blocks as `SUBNET_CIDR_1` and `SUBNET_CIDR_2`. In the public-subnet layout, the last column must be `True`.

> **Note:** The chart lists each subnet with both its `id` and its IPv4 `cidrBlock`. CAPA matches each listed subnet to the subnets in the VPC by ID or by CIDR block. A subnet listed by ID alone has an empty CIDR block, and an IPv6-only subnet also has an empty IPv4 CIDR block, so CAPA can pick an IPv6-only subnet in the VPC instead of the one you listed. Step 9.3 shows what that looks like.

> **Note:** CAPA v2.11.1 treats a subnet that uses the VPC's main route table, with no route table of its own, as private, even when the main route table has an internet-gateway route. In the public-subnet layout, the nodes get their public IP addresses because the subnet auto-assigns them. Do not set `publicIP: true` on the machine templates for such subnets. The chart in Step 4 leaves it unset.

> **Note:** The chart's AWS cloud controller manager runs with `--configure-cloud-routes=false` (Step 4.6). The CAPA documentation states that route tables need the `kubernetes.io/cluster/CLUSTER_NAME` tag only when that setting is not used, so the route tables do not need it.

#### 3.3 Verification Checklist

- [ ] VPC found: `aws ec2 describe-vpcs --vpc-ids VPC_ID --query 'Vpcs[].[VpcId,InstanceTenancy,CidrBlock]' --output table` shows one row with your VPC ID
- [ ] Tenancy known: the same command shows `default` or `dedicated` in the tenancy column
- [ ] Subnets found: the `describe-subnets` command in Step 3.2 shows both subnets with an IPv4 CIDR block
- [ ] Internet route: the **Route table** tab of each subnet in the AWS console shows a `0.0.0.0/0` route to a NAT gateway (private layout) or to an internet gateway (public layout)

---

### Step 4 — Write the Cluster Template Chart

*You are here: Step 4 of 9. Run on: the admin host.*

You now write the Helm chart that describes the whole cluster. It has one settings file (`values.yaml`) and four templates. When you install it, it creates the Rancher `Cluster`, the CAPA `AWSCluster`, and one `AWSMachineTemplate` per machine pool. The machine templates are where `tenancy: dedicated` is set. The `Cluster` also carries a `HelmChart` for the AWS cloud controller manager, which connects Kubernetes to AWS.

![What helm install creates: the chart capa-dedicated-rke2 (Chart.yaml, values.yaml, templates/_helpers.tpl, templates/awscluster.yaml, templates/machinetemplates.yaml, templates/cluster.yaml) is installed into namespace fleet-default, creating Cluster capadt (provisioning.cattle.io/v1, v1.35.9+rke2r1, pools cp, wd and ws, AWS CCM HelmChart 0.0.12), which points with infrastructureRef to AWSCluster capadt (region us-east-1, internal NLB, existing VPC_ID, 2 existing subnets given by id and cidrBlock) and with machineConfigRef to three AWSMachineTemplates: capadt-cp-6214a508 m5.large dedicated, capadt-wd-327e147f m5.large dedicated and capadt-ws-1d42237e t3.medium dedicated; each template name is the cluster name plus the pool name plus an 8-character hash of ami, sshKeyName, instanceType, iamInstanceProfile and tenancy](assets/dedicated-tenancy-beginner-05-chart-objects.png)

#### 4.1 Create the Chart Folder and Chart.yaml

**What this does:** Creates the chart folder, moves into it, and writes `Chart.yaml`, the chart's name card. The annotations make Rancher treat it as a cluster template.

```bash
mkdir -p capa-dedicated-rke2/templates && cd capa-dedicated-rke2
cat > Chart.yaml <<'EOF'
apiVersion: v2
name: capa-dedicated-rke2
description: RKE2 cluster provisioned by Rancher with the native CAPA infrastructure provider on EC2 Dedicated Instances
type: application
version: 0.1.0
annotations:
  catalog.cattle.io/type: cluster-template     # Rancher lists the chart as a cluster template
  catalog.cattle.io/namespace: fleet-default   # Rancher installs cluster templates into fleet-default
EOF
```

#### 4.2 Write values.yaml

**What this does:** Writes your settings. The top-level `tenancy: dedicated` applies to every pool that does not set its own value. The `wd` and `ws` pools also say `dedicated`, so all three pools are dedicated.

```bash
cat > values.yaml <<'EOF'
cluster:
  name: CLUSTER_NAME
  kubernetesVersion: KUBERNETES_VERSION
  region: CAPA_REGION
  identity: CREDENTIAL_SECRET_ID    # AWSClusterStaticIdentity mirrored from the Rancher AWS cloud credential (Step 2)
  sshKeyName: SSH_KEY_NAME
  ami: AMI_ID                       # Ubuntu 24.04 LTS in CAPA_REGION
  vpcId: VPC_ID                     # existing VPC; CAPA does not create one
  subnets:                          # existing subnets: give the ID and the IPv4 CIDR block of each
    - id: SUBNET_ID_1
      cidrBlock: SUBNET_CIDR_1
    - id: SUBNET_ID_2
      cidrBlock: SUBNET_CIDR_2
  additionalTags:
    Project: PROJECT_TAG

# Default tenancy for pools that do not set their own: default | dedicated
tenancy: dedicated

# AWS cloud controller manager chart version, matched to the downstream Kubernetes minor version (v1.35)
ccmChartVersion: 0.0.12

pools:
  - name: cp                        # control plane and etcd
    controlPlane: true
    etcd: true
    worker: false
    quantity: 1
    instanceType: m5.large
    iamInstanceProfile: CONTROL_PLANE_INSTANCE_PROFILE
    # tenancy omitted: inherits the top-level value (dedicated)
  - name: wd                        # first worker pool
    controlPlane: false
    etcd: false
    worker: true
    quantity: 1
    instanceType: m5.large
    iamInstanceProfile: NODES_INSTANCE_PROFILE
    tenancy: dedicated
  - name: ws                        # second worker pool
    controlPlane: false
    etcd: false
    worker: true
    quantity: 1
    instanceType: t3.medium
    iamInstanceProfile: NODES_INSTANCE_PROFILE
    tenancy: dedicated
EOF
```

Now replace every placeholder in `values.yaml` with your own value. The checklist in Step 4.8 confirms none are left.

> **Note:** A pool's own `tenancy` wins over the top-level `tenancy`. Set the top-level value for most pools, and set `tenancy` on a pool only when it differs.

> **Note:** `t3.medium` launches with dedicated tenancy in `us-east-1`.

#### 4.3 Write the Name Helper

**What this does:** Writes a small helper that names each machine template. The name ends with a short fingerprint (hash) of the template's settings.

```bash
cat > templates/_helpers.tpl <<'EOF'
{{/*
AWSMachineTemplate name for a pool. AWSMachineTemplate is immutable, so the name carries a
hash of exactly the fields that go into the template spec: a changed spec gets a new name and
Rancher rolls only the pool that references it. quantity and roles are left out, so scaling a
pool does not replace its machines.
Call with (dict "pool" $pool "root" $).
*/}}
{{- define "capadt.templateName" -}}
{{- $p := .pool -}}
{{- $v := .root.Values -}}
{{- $spec := dict "ami" $v.cluster.ami "ssh" $v.cluster.sshKeyName "type" $p.instanceType "profile" $p.iamInstanceProfile "tenancy" ($p.tenancy | default $v.tenancy) -}}
{{- printf "%s-%s-%s" $v.cluster.name $p.name ($spec | toJson | sha256sum | trunc 8) -}}
{{- end -}}
EOF
```

> **Note:** An AWSMachineTemplate cannot be changed after it is created. Kubernetes rejects any edit to its `spec`. So the name includes an 8-character hash of the settings that go into it: `ami`, `sshKeyName`, `instanceType`, `iamInstanceProfile` and the pool's tenancy. Change one of those, and the template gets a new name. Helm then creates a new template, and Rancher replaces only the machines of that pool. `quantity` and the pool roles are not part of the hash, so changing the number of machines does not replace the existing ones.

#### 4.4 Write the AWSCluster Template

**What this does:** Describes the AWS side of the cluster: the region, the identity from Step 2, an internal load balancer, your existing VPC and subnets (each with its ID and IPv4 CIDR block), and the firewall ports the nodes need to talk to each other.

```bash
cat > templates/awscluster.yaml <<'EOF'
apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
kind: AWSCluster
metadata:
  name: {{ .Values.cluster.name }}
  namespace: {{ .Release.Namespace }}
spec:
  region: {{ .Values.cluster.region }}
  identityRef:
    kind: AWSClusterStaticIdentity
    name: {{ .Values.cluster.identity }}
  # Tags every AWS resource CAPA creates, including the instances
  additionalTags:
    {{- toYaml .Values.cluster.additionalTags | nindent 4 }}
  controlPlaneLoadBalancer:
    loadBalancerType: nlb
    healthCheckProtocol: TCP
    scheme: internal                 # nodes join through the VPC, not over the internet
  network:
    vpc:
      id: {{ .Values.cluster.vpcId }}    # existing VPC: CAPA uses it and creates no VPC, subnets or NAT gateways
    subnets:                             # existing subnets: id and IPv4 CIDR of each
      {{- range .Values.cluster.subnets }}
      - id: {{ .id }}
        cidrBlock: {{ .cidrBlock }}
      {{- end }}
    additionalNodeIngressRules:
      - description: RKE2 supervisor API
        protocol: tcp
        fromPort: 9345
        toPort: 9345
        sourceSecurityGroupRoles: [controlplane, node]
      - description: etcd client and peer
        protocol: tcp
        fromPort: 2379
        toPort: 2380
        sourceSecurityGroupRoles: [controlplane, node]
    cni:
      cniIngressRules:
        - description: Calico VXLAN
          protocol: udp
          fromPort: 4789
          toPort: 4789
        - description: Calico Typha
          protocol: tcp
          fromPort: 5473
          toPort: 5473
EOF
```

> **Note:** With `vpc.id` and `subnets` set, CAPA uses your VPC and subnets and does not create a new VPC, new subnets or other network resources. It still creates the control-plane load balancer and the security groups. It also tags the subnets you list with `kubernetes.io/cluster/CLUSTER_NAME` = `shared`, `kubernetes.io/role/internal-elb` = `1` and your `additionalTags`, and it does not remove those tags when the cluster is deleted (Step 8.4).
>
> The `additionalNodeIngressRules` and `cniIngressRules` open the RKE2 supervisor port (9345), the etcd ports (2379 to 2380), and the Calico VXLAN (UDP 4789) and Typha (TCP 5473) ports between the cluster's nodes.

> **STIG:** CAPA's node security group (`CLUSTER_NAME-node`) opens TCP 30000 to 32767, the NodePort service range, to `0.0.0.0/0`. In public subnets the nodes have public IP addresses, so any NodePort service is reachable from the internet. The API server load balancer's security group also opens TCP 6443 to `0.0.0.0/0`, but the load balancer is internal. The tradeoff is that the public-subnet layout is simpler, while the private-subnet layout keeps the nodes off the internet. Use private subnets, or restrict the NodePort rule in the `CLUSTER_NAME-node` security group to the addresses that need it.

#### 4.5 Write the AWSMachineTemplate Template

**What this does:** Describes one EC2 server design per pool: the AMI, the instance type, the **tenancy**, the instance profile, the SSH key and a 40 GiB disk.

```bash
cat > templates/machinetemplates.yaml <<'EOF'
{{- range $pool := .Values.pools }}
---
apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
kind: AWSMachineTemplate
metadata:
  name: {{ include "capadt.templateName" (dict "pool" $pool "root" $) }}
  namespace: {{ $.Release.Namespace }}
spec:
  template:
    spec:
      ami:
        id: {{ $.Values.cluster.ami }}
      instanceType: {{ $pool.instanceType }}
      tenancy: {{ $pool.tenancy | default $.Values.tenancy }}   # default | dedicated
      iamInstanceProfile: {{ $pool.iamInstanceProfile }}
      sshKeyName: {{ $.Values.cluster.sshKeyName }}
      privateDnsName:
        hostnameType: resource-name
      rootVolume:
        size: 40                     # root volume size in GiB
      cloudInit:
        insecureSkipSecretsManager: true   # stock Ubuntu AMI has no Secrets Manager user-data source
{{- end }}
EOF
```

> **Note:** Rancher requires each machine pool to use its own machine template. This chart makes one template per pool.

#### 4.6 Write the Cluster Template

**What this does:** Describes the Rancher cluster: the RKE2 version, the link to the AWSCluster, the three machine pools and their templates, the Calico network plugin, and the AWS cloud controller manager.

```bash
cat > templates/cluster.yaml <<'EOF'
apiVersion: provisioning.cattle.io/v1
kind: Cluster
metadata:
  name: {{ .Values.cluster.name }}
  namespace: {{ .Release.Namespace }}
spec:
  kubernetesVersion: {{ .Values.cluster.kubernetesVersion }}
  rkeConfig:
    infrastructureRef:
      apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
      kind: AWSCluster
      name: {{ .Values.cluster.name }}
      namespace: {{ .Release.Namespace }}
    machinePools:
      {{- range $pool := .Values.pools }}
      - name: {{ $pool.name }}
        controlPlaneRole: {{ $pool.controlPlane }}
        etcdRole: {{ $pool.etcd }}
        workerRole: {{ $pool.worker }}
        quantity: {{ $pool.quantity }}
        drainBeforeDelete: true      # cordon and drain a node before its machine is deleted during a roll
        machineConfigRef:
          apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
          kind: AWSMachineTemplate
          name: {{ include "capadt.templateName" (dict "pool" $pool "root" $) }}
          namespace: {{ $.Release.Namespace }}
      {{- end }}
    machineGlobalConfig:
      cni: calico
      cloud-provider-name: external
    machineSelectorConfig:
      - config:
          disable-cloud-controller: true
        machineLabelSelector:
          matchExpressions:
            - key: rke.cattle.io/control-plane-role
              operator: In
              values: ["true"]
      - config:
          disable-cloud-controller: true
        machineLabelSelector:
          matchExpressions:
            - key: rke.cattle.io/etcd-role
              operator: In
              values: ["true"]
    additionalManifest: |-
      apiVersion: helm.cattle.io/v1
      kind: HelmChart
      metadata:
        name: aws-cloud-controller-manager
        namespace: kube-system
      spec:
        chart: aws-cloud-controller-manager
        repo: https://kubernetes.github.io/cloud-provider-aws
        version: {{ .Values.ccmChartVersion }}
        targetNamespace: kube-system
        bootstrap: true
        valuesContent: |-
          hostNetworking: true
          nodeSelector:
            node-role.kubernetes.io/control-plane: "true"
          args:
            - --configure-cloud-routes=false
            - --v=2
            - --cloud-provider=aws
          tolerations:
            - key: node.cloudprovider.kubernetes.io/uninitialized
              value: "true"
              effect: NoSchedule
            - key: node-role.kubernetes.io/master
              effect: NoSchedule
            - key: node-role.kubernetes.io/control-plane
              effect: NoSchedule
            - key: node-role.kubernetes.io/etcd
              effect: NoExecute
EOF
```

> **Note:** The AWS cloud controller manager is pinned to chart 0.0.12, whose appVersion is v1.35.0, to match the cluster's Kubernetes minor version v1.35. If you change `kubernetesVersion` to a different minor version, change `ccmChartVersion` too.

#### 4.7 Lint the Chart

**What this does:** Moves back out of the chart folder and checks the chart for mistakes.

```bash
cd .. && helm lint capa-dedicated-rke2
```

Expected output:
```
==> Linting capa-dedicated-rke2
[INFO] Chart.yaml: icon is recommended

1 chart(s) linted, 0 chart(s) failed
```

#### 4.8 Verification Checklist

- [ ] Files present: `ls capa-dedicated-rke2/templates` lists `_helpers.tpl`, `awscluster.yaml`, `cluster.yaml` and `machinetemplates.yaml`
- [ ] Chart lints: `helm lint capa-dedicated-rke2` reports `0 chart(s) failed`
- [ ] Placeholders replaced: `grep -nE '[A-Z]+_[A-Z_]+' capa-dedicated-rke2/values.yaml` returns no lines
- [ ] All pools dedicated: `grep -n "tenancy:" capa-dedicated-rke2/values.yaml` shows `dedicated` on every `tenancy` line

---

### Step 5 — Install the Cluster Template

*You are here: Step 5 of 9. Run on: the admin host.*

You first preview the template names, then install the chart into `fleet-default`. Rancher reads the `Cluster` object from that namespace and starts building.

#### 5.1 Preview the Template Names

**What this does:** Renders the chart without installing it, and shows only the machine template names.

```bash
helm template CLUSTER_NAME capa-dedicated-rke2 -n fleet-default | grep "^  name: CLUSTER_NAME-"
```

Expected output lists one name per pool, each ending with the hash of its settings:
```
  name: capadt-cp-6214a508
  name: capadt-wd-327e147f
  name: capadt-ws-1d42237e
```

#### 5.2 Install the Chart

**What this does:** Installs the chart as a Helm release named after your cluster. This starts the build.

```bash
helm install CLUSTER_NAME capa-dedicated-rke2 -n fleet-default
```

Expected output:
```
NAME: capadt
LAST DEPLOYED: [timestamp]
NAMESPACE: fleet-default
STATUS: deployed
REVISION: 1
TEST SUITE: None
```

#### 5.3 Check the Objects

**What this does:** Lists the Rancher cluster, the AWSCluster and the machine templates.

```bash
kubectl -n fleet-default get clusters.provisioning.cattle.io,awsclusters,awsmachinetemplates
```

Right after the install, the output lists the three kinds of object with empty `READY` columns. Once the cluster is ready (Step 6), the output looks like this:
```
NAME                                    VERSION          CLUSTER NAME   AGE   KUBECONFIG          READY
cluster.provisioning.cattle.io/capadt   v1.35.9+rke2r1   c-m-nvfbpsr6   20m   capadt-kubeconfig   true

NAME                                                CLUSTER   READY   VPC                     BASTION IP   BASTION IPV6
awscluster.infrastructure.cluster.x-k8s.io/capadt   capadt    true    vpc-03d91b25c85f6c6a6                

NAME                                                                    AGE
awsmachinetemplate.infrastructure.cluster.x-k8s.io/capadt-cp-6214a508   20m
awsmachinetemplate.infrastructure.cluster.x-k8s.io/capadt-wd-327e147f   20m
awsmachinetemplate.infrastructure.cluster.x-k8s.io/capadt-ws-1d42237e   20m
```

The value in the CLUSTER NAME column (here `c-m-nvfbpsr6`) is `MGMT_CLUSTER_ID`. Write it down for Step 6.2.

> **Note:** To change the cluster later, edit `values.yaml` and run `helm upgrade CLUSTER_NAME capa-dedicated-rke2 -n fleet-default`. A change to a pool's `instanceType` or `tenancy` gives only that pool's template a new name, so only that pool's machines are replaced. Do not edit an existing AWSMachineTemplate with `kubectl edit` or `kubectl patch`. Kubernetes rejects it with `AWSMachineTemplate.Spec is immutable`.

> **Note:** The source article [CAPA Dedicated Tenancy Cluster Template](../infra/CAPA_Dedicated_Tenancy_Cluster_Template.md) also shows how to list this chart on the Rancher **Create** cluster page through a ClusterRepo. This guide installs it with the Helm CLI only.

#### 5.4 Verification Checklist

- [ ] Release deployed: `helm list -n fleet-default` shows `capadt` with `STATUS deployed`
- [ ] Cluster object exists: `kubectl -n fleet-default get clusters.provisioning.cattle.io capadt` returns one row
- [ ] Three templates exist: `kubectl -n fleet-default get awsmachinetemplates` lists `capadt-cp-6214a508`, `capadt-wd-327e147f` and `capadt-ws-1d42237e`

---

### Step 6 — Wait for the Cluster to Become Active

*You are here: Step 6 of 9. Run on: the admin host and your browser.*

Building takes about 9 minutes when nothing goes wrong. You check three things in order: the AWS side, the Rancher cluster, and the machines.

#### 6.1 Wait for the AWSCluster

**What this does:** Shows whether CAPA has finished the AWS side of the cluster, and which VPC it uses.

```bash
kubectl -n fleet-default get awscluster CLUSTER_NAME
```

Expected output shows `READY true` and your VPC ID:
```
NAME     CLUSTER   READY   VPC                     BASTION IP   BASTION IPV6
capadt   capadt    true    vpc-03d91b25c85f6c6a6
```

> **Note:** If the AWSCluster stays `READY false`, see Step 9.3.

#### 6.2 Wait for Rancher to Report the Cluster Ready

The `READY` column of the provisioning `Cluster` can say `true` before the cluster is really ready. Check Rancher's own `Ready` condition instead.

**What this does:** Prints the `Ready` condition of the cluster as Rancher sees it.

```bash
kubectl get clusters.management.cattle.io MGMT_CLUSTER_ID -o jsonpath='{.status.conditions[?(@.type=="Ready")]}'
```

Expected output has `"status":"True"`:
```
{"lastUpdateTime":"[timestamp]","status":"True","type":"Ready"}
```

#### 6.3 Check the Machines

**What this does:** Lists the Cluster API machines, one per EC2 server.

```bash
kubectl -n fleet-default get machines
```

Expected output lists three machines, one per pool, each with `READY True` and `PHASE Running`:
```
NAME                    CLUSTER   NODE NAME             FAILURE DOMAIN   READY   AVAILABLE   UP-TO-DATE   PHASE     AGE   VERSION
capadt-cp-h7ksx-gk4cq   capadt    i-0c758b7c808d024ef                    True    True        True         Running   20m   
capadt-wd-blvsk-b7fh5   capadt    i-0356b0c4190dd2fa6                    True    True        True         Running   20m   
capadt-ws-w9lxx-c64xc   capadt    i-045b4e7c6d9c44ce0                    True    True        True         Running   20m   
```

The `NODE NAME` column shows the EC2 instance IDs. The `FAILURE DOMAIN` and `VERSION` columns stay empty for these machines.

#### 6.4 Check the Cluster in the Rancher UI

Open **Cluster Management** in the Rancher UI. The `capadt` cluster shows **Active**, with Provider `awsmachinetemplate`, Distro RKE2, version v1.35.9+rke2r1, and three machines.

![Rancher v2.15.2 Cluster Management Clusters list showing capadt as Active with provider awsmachinetemplate, distro RKE2, version v1.35.9+rke2r1 and 3 machines, next to the local cluster as Active on v1.36.4+rke2r1](assets/dedicated-tenancy-beginner-06-cluster-active.png)

#### 6.5 Check the Machine Pools in the Rancher UI

Select `capadt`. The **Machine Pools** tab lists three pools, each with one Running machine: `capadt-cp` (Control Plane, Etcd), `capadt-wd` (Worker) and `capadt-ws` (Worker). Each machine shows an external and an internal IP address. The external addresses come from the subnets' automatic public IPv4 setting. This page does not show tenancy. Step 7.4 checks tenancy in AWS.

![Rancher cluster detail page for capadt in Active state, with machine provider awsmachinetemplate and Kubernetes version v1.35.9+rke2r1; the Machine Pools tab lists the pools capadt-cp, capadt-wd and capadt-ws, each with one Running machine showing its EC2 instance ID, an external and internal IP address, and the roles Control Plane, Etcd for capadt-cp and Worker for capadt-wd and capadt-ws](assets/dedicated-tenancy-beginner-07-machine-pools.png)

#### 6.6 Verification Checklist

- [ ] AWSCluster ready: `kubectl -n fleet-default get awscluster CLUSTER_NAME` shows `READY true` and your `VPC_ID`
- [ ] Rancher reports ready: the command in Step 6.2 prints `"status":"True"`
- [ ] Machines running: `kubectl -n fleet-default get machines` shows three rows with `PHASE Running` and `READY True`
- [ ] Cluster Active in Rancher: **Cluster Management** shows `capadt` with state **Active**

---

### Step 7 — Check That Every Node Is Dedicated

*You are here: Step 7 of 9. Run on: the admin host (Kubernetes checks) and your workstation (AWS check in Step 7.4).*

You look at the new cluster from the inside, then ask AWS for the tenancy of each server.

#### 7.1 Save the New Cluster's Kubeconfig

**What this does:** Reads the new cluster's kubeconfig from Rancher, saves it as `ds.kubeconfig`, and makes it readable only by you.

```bash
kubectl -n fleet-default get secret CLUSTER_NAME-kubeconfig -o jsonpath='{.data.value}' | base64 -d > ds.kubeconfig && chmod 600 ds.kubeconfig
```

Expected output: none.

#### 7.2 Check the Nodes

**What this does:** Lists the new cluster's nodes with their roles, versions and IP addresses.

```bash
kubectl --kubeconfig ds.kubeconfig get nodes -o wide
```

Expected output lists three nodes, all `Ready`. The control-plane node has the roles `control-plane,etcd`, and the two workers have the role `worker`. In the public-subnet layout, the `EXTERNAL-IP` column shows each node's public address:
```
NAME                  STATUS   ROLES                AGE   VERSION          INTERNAL-IP     EXTERNAL-IP      OS-IMAGE             KERNEL-VERSION   CONTAINER-RUNTIME
i-0356b0c4190dd2fa6   Ready    worker               12m   v1.35.9+rke2r1   172.31.27.46    54.175.151.155   Ubuntu 24.04.5 LTS   7.0.0-1014-aws   containerd://2.2.7-k3s1
i-045b4e7c6d9c44ce0   Ready    worker               12m   v1.35.9+rke2r1   172.31.20.16    54.196.143.162   Ubuntu 24.04.5 LTS   7.0.0-1014-aws   containerd://2.2.7-k3s1
i-0c758b7c808d024ef   Ready    control-plane,etcd   15m   v1.35.9+rke2r1   172.31.19.116   18.234.46.96     Ubuntu 24.04.5 LTS   7.0.0-1014-aws   containerd://2.2.7-k3s1
```

#### 7.3 Check the Instance Types and Zones

**What this does:** Lists the nodes with two extra columns: the EC2 instance type and the availability zone.

```bash
kubectl --kubeconfig ds.kubeconfig get nodes -L node.kubernetes.io/instance-type,topology.kubernetes.io/zone
```

Expected output shows the instance type and zone of each node. All three nodes are in `us-east-1a`, the zone of the first listed subnet, because the machines have no failure domain:
```
NAME                  STATUS   ROLES                AGE   VERSION          INSTANCE-TYPE   ZONE
i-0356b0c4190dd2fa6   Ready    worker               12m   v1.35.9+rke2r1   m5.large        us-east-1a
i-045b4e7c6d9c44ce0   Ready    worker               12m   v1.35.9+rke2r1   t3.medium       us-east-1a
i-0c758b7c808d024ef   Ready    control-plane,etcd   15m   v1.35.9+rke2r1   m5.large        us-east-1a
```

#### 7.4 Check the Tenancy of Each Instance

Run this on your workstation.

**What this does:** Asks AWS for every running instance with your `Project` tag, and shows its ID, type, tenancy, zone and name.

```bash
aws ec2 describe-instances --filters Name=tag:Project,Values=PROJECT_TAG Name=instance-state-name,Values=pending,running --query 'Reservations[].Instances[].[InstanceId,InstanceType,Placement.Tenancy,Placement.AvailabilityZone,Tags[?Key==`Name`]|[0].Value]' --output table
```

Expected output lists one row per machine, and the tenancy column says `dedicated` on all three. If another instance carries the same `Project` tag, it appears in the table too.
```
------------------------------------------------------------------------------------------
|                                    DescribeInstances                                   |
+----------------------+------------+------------+-------------+-------------------------+
|  i-0c758b7c808d024ef |  m5.large  |  dedicated |  us-east-1a |  capadt-cp-h7ksx-gk4cq  |
|  i-0356b0c4190dd2fa6 |  m5.large  |  dedicated |  us-east-1a |  capadt-wd-blvsk-b7fh5  |
|  i-045b4e7c6d9c44ce0 |  t3.medium |  dedicated |  us-east-1a |  capadt-ws-w9lxx-c64xc  |
+----------------------+------------+------------+-------------+-------------------------+
```

#### 7.5 Run a Test Web App on Two Workers

Back on the admin host.

**What this does:** Starts two copies of the nginx web server (version 1.27.5, pinned) on the new cluster.

```bash
kubectl --kubeconfig ds.kubeconfig create deployment web --image=nginx:1.27.5-alpine --replicas=2
```

Expected output:
```
deployment.apps/web created
```

**What this does:** Gives the two web servers one shared name and port inside the cluster (a Service).

```bash
kubectl --kubeconfig ds.kubeconfig expose deployment web --port 80
```

Expected output:
```
service/web exposed
```

**What this does:** Shows where the two web server pods are running.

```bash
kubectl --kubeconfig ds.kubeconfig get pods -l app=web -o wide
```

Expected output shows two Running pods, one on each worker. The control-plane node carries the taints `node-role.kubernetes.io/control-plane:NoSchedule` and `node-role.kubernetes.io/etcd:NoExecute`, which keep app pods off it. `...` stands for the RESTARTS and AGE columns:
```
NAME                  READY   STATUS    RESTARTS   AGE   IP             NODE                  NOMINATED NODE   READINESS GATES
web-b54448854-9jzxc   1/1     Running   ...        ...   10.42.67.13    i-0356b0c4190dd2fa6   <none>           <none>
web-b54448854-c8mcq   1/1     Running   ...        ...   10.42.199.79   i-045b4e7c6d9c44ce0   <none>           <none>
```

#### 7.6 Check That the Nodes Can Talk to Each Other

**What this does:** Starts a temporary busybox pod that fetches the web page four times through the Service, prints each page title, then deletes itself.

```bash
kubectl --kubeconfig ds.kubeconfig run curl --image=busybox:1.37.0 --restart=Never --rm -i --command -- sh -c 'for i in 1 2 3 4; do wget -qO- -T5 http://web.default.svc.cluster.local | grep -o "<title>.*</title>"; done'
```

Expected output shows the nginx title four times, then the deletion of the temporary pod:
```
<title>Welcome to nginx!</title>
<title>Welcome to nginx!</title>
<title>Welcome to nginx!</title>
<title>Welcome to nginx!</title>
pod "curl" deleted from default namespace
```

#### 7.7 Verification Checklist

- [ ] Nodes ready: `kubectl --kubeconfig ds.kubeconfig get nodes` lists three nodes with `STATUS Ready` and `VERSION v1.35.9+rke2r1`
- [ ] Instance types: `kubectl --kubeconfig ds.kubeconfig get nodes -L node.kubernetes.io/instance-type` shows `m5.large` for the control plane and the `wd` worker, and `t3.medium` for the `ws` worker
- [ ] Every node dedicated: the `describe-instances` command in Step 7.4 shows `dedicated` for `capadt-cp`, `capadt-wd` and `capadt-ws`
- [ ] Networking across nodes: the `curl` pod in Step 7.6 prints the nginx title four times
- [ ] Cloud provider set: `kubectl --kubeconfig ds.kubeconfig get nodes -o jsonpath='{.items[*].spec.providerID}'` prints one `aws:///us-east-1a/i-...` value per node

---

### Step 8 — Delete the Cluster

*You are here: Step 8 of 9. Run on: the admin host, then your workstation for Steps 8.3 and 8.4.*

Uninstalling the Helm release deletes the `Cluster`, `AWSCluster` and `AWSMachineTemplate` objects together. Rancher and CAPA then remove the machines, the EC2 instances, and the load balancer and security groups that CAPA created. Your VPC, subnets and route tables stay. The tags CAPA added to your subnets also stay, so you remove them yourself in Step 8.4.

#### 8.1 Uninstall the Release

**What this does:** Removes the Helm release, which starts the deletion of the whole cluster.

```bash
helm uninstall CLUSTER_NAME -n fleet-default
```

Expected output:
```
release "CLUSTER_NAME" uninstalled
```

#### 8.2 Wait for the Cluster Objects to Be Removed

**What this does:** Lists any cluster objects that are still being deleted.

```bash
kubectl -n fleet-default get clusters.provisioning.cattle.io,awsclusters,machines
```

Expected output, about 3 minutes after the uninstall:
```
No resources found in fleet-default namespace.
```

Until then, the command lists the objects still being deleted.

#### 8.3 Confirm the Instances Are Gone and Your VPC Remains

Run these on your workstation.

**What this does:** Lists the state of every instance whose name starts with your cluster name.

```bash
aws ec2 describe-instances --filters Name=tag:Name,Values='CLUSTER_NAME-*' --query 'Reservations[].Instances[].State.Name' --output text
```

Expected output, one word per instance:
```
terminated	terminated	terminated
```

**What this does:** Asks AWS for your VPC, to confirm it was left in place.

```bash
aws ec2 describe-vpcs --vpc-ids VPC_ID --query 'Vpcs[].[VpcId,InstanceTenancy,CidrBlock]' --output table
```

Expected output is the same table as in Step 3.1:
```
-------------------------------------------------------
|                    DescribeVpcs                     |
+------------------------+----------+-----------------+
|  vpc-03d91b25c85f6c6a6 |  default |  172.31.0.0/16  |
+------------------------+----------+-----------------+
```

CAPA has also deleted the load balancer and the security groups it created. No security group whose name starts with `CLUSTER_NAME-` is left.

#### 8.4 Remove the Tags CAPA Added to Your Subnets

> **Note:** Remove only tags that your subnets did not carry before this guide. If your subnets already had `kubernetes.io/role/internal-elb` (for example, for another cluster), leave that key out of the command.

**What this does:** Deletes the cluster tag, the internal load balancer tag and the `Project` tag from your two subnets.

```bash
aws ec2 delete-tags --resources SUBNET_ID_1 SUBNET_ID_2 --tags Key=kubernetes.io/cluster/CLUSTER_NAME Key=kubernetes.io/role/internal-elb Key=Project
```

Expected output: none.

**What this does:** Shows the tags that remain on the two subnets.

```bash
aws ec2 describe-subnets --subnet-ids SUBNET_ID_1 SUBNET_ID_2 --query 'Subnets[].[SubnetId,Tags]'
```

Expected output lists each subnet ID with its remaining tags. A subnet that had no tags before this guide shows `null` for its tags.

> **Note:** `helm uninstall` does not remove the cloud credential, the `AWSClusterStaticIdentity`, the CAPA provider, the IAM instance profiles and access key, or your VPC and subnets. Remove those separately when nothing else uses them.

#### 8.5 Verification Checklist

- [ ] Release removed: `helm list -n fleet-default` no longer lists `CLUSTER_NAME`
- [ ] Objects removed: `kubectl -n fleet-default get clusters.provisioning.cattle.io,awsclusters,machines` returns `No resources found in fleet-default namespace.`
- [ ] Instances terminated: `aws ec2 describe-instances --filters Name=tag:Name,Values='CLUSTER_NAME-*' --query 'Reservations[].Instances[].State.Name' --output text` prints only `terminated`
- [ ] VPC kept: `aws ec2 describe-vpcs --vpc-ids VPC_ID --query 'Vpcs[].[VpcId,InstanceTenancy,CidrBlock]' --output table` still shows your VPC
- [ ] Subnet tags removed: `aws ec2 describe-subnets --subnet-ids SUBNET_ID_1 SUBNET_ID_2 --query 'Subnets[].[SubnetId,Tags]'` no longer shows `kubernetes.io/cluster/CLUSTER_NAME`

---

### Step 9 — Troubleshoot Common Problems

*You are here: Step 9 of 9. Run each command where the failing step ran.*

Each problem below lists what you see, why it happens, and how to fix it. Try the fixes in order. The first one is the quickest check.

#### 9.1 `the server doesn't have a resource type "capiproviders"`

**Symptom:** `kubectl get capiproviders -A` returns `error: the server doesn't have a resource type "capiproviders"`.

**Cause:** Rancher installs Turtles and Cluster API core a few minutes after the first login, and the `CAPIProvider` type does not exist until then.

**Resolution:**

1. Check whether Turtles is installed yet:
   ```bash
   helm list -n cattle-turtles-system
   ```
   Expected: a `rancher-turtles` row with `STATUS deployed`. An empty list means Turtles is not installed yet. Wait about four minutes and check again. If the list stays empty, confirm that the first login in the Rancher UI is complete. Rancher installs Turtles a few minutes after it.

2. When the release is listed, check the core provider:
   ```bash
   kubectl get capiproviders -A
   ```
   Expected: a `cluster-api` row with `PHASE Ready`.

#### 9.2 `No resources found` for the Identity After Creating the Cloud Credential

**Symptom:** `kubectl get awsclusterstaticidentities` returns `No resources found` more than 30 seconds after you created the cloud credential.

**Cause:** The credential's Secret is missing the `provisioning.cattle.io/driver: aws` annotation, or the `aws` CAPIProvider is not `Ready`, and Turtles needs both.

**Resolution:**

1. Check the Secret's annotations:
   ```bash
   kubectl -n cattle-global-data get secret CREDENTIAL_SECRET_ID -o jsonpath='{.metadata.annotations}'
   ```
   Expected: no `provisioning.cattle.io/driver` key in the output.

2. Check the `aws` CAPIProvider:
   ```bash
   kubectl get capiproviders -n capa-system aws
   ```
   Expected: `PHASE Ready`. If it is not `Ready`, fix the provider from Step 1 first.

3. Add the annotation:
   ```bash
   kubectl -n cattle-global-data annotate secret CREDENTIAL_SECRET_ID provisioning.cattle.io/driver=aws
   ```
   Expected output: `secret/cc-a1b2c annotated`

4. Wait about 10 seconds and check the identity:
   ```bash
   kubectl get awsclusterstaticidentities
   ```
   Expected: a row named `CREDENTIAL_SECRET_ID`.

#### 9.3 AWSCluster Shows `LoadBalancerFailed` and a Subnet You Did Not List

**Symptom:** The AWSCluster stays `READY false`. Its `LoadBalancerReady` condition is `False` with reason `LoadBalancerFailed` and a message that starts with `failed to create load balancer:` and names a list of subnets, for example `[subnet-06e163a2140f18e22 subnet-074ee3fa0d6360110]`, where one ID is a subnet you never listed. On the first try, the message can also contain `api error Throttling: Rate exceeded` from AWS.

**Cause:** The chart lists a subnet by `id` without its `cidrBlock`, so CAPA matched it to a subnet with an empty IPv4 CIDR block, such as an IPv6-only subnet in the same VPC, instead of the subnet you listed.

**Resolution:**

1. Read the AWSCluster conditions:
   ```bash
   kubectl -n fleet-default get awscluster CLUSTER_NAME -o jsonpath='{range .status.conditions[*]}{.type}={.status} {.reason} {.message}{"\n"}{end}'
   ```
   Expected: a `LoadBalancerReady=False LoadBalancerFailed failed to create load balancer: ...` line that names a subnet ID that is not in your `values.yaml`.

2. Open `capa-dedicated-rke2/values.yaml` and check that every `- id:` entry under `subnets` has a `cidrBlock:` line under it. Add any that are missing, with the subnet's IPv4 CIDR block from Step 3.2.

3. Remove the failed cluster:
   ```bash
   helm uninstall CLUSTER_NAME -n fleet-default
   ```
   Expected: `release "CLUSTER_NAME" uninstalled`.

4. Wait until the cluster objects are gone:
   ```bash
   kubectl -n fleet-default get clusters.provisioning.cattle.io,awsclusters,machines
   ```
   Expected: `No resources found in fleet-default namespace.`

5. Install the corrected chart:
   ```bash
   helm install CLUSTER_NAME capa-dedicated-rke2 -n fleet-default
   ```
   Expected: `STATUS: deployed` and `REVISION: 1`. Continue with Step 6.

6. CAPA also tagged the wrong subnet with `kubernetes.io/cluster/CLUSTER_NAME`, `kubernetes.io/role/internal-elb` and your `Project` tag. Remove those tags from it with the `aws ec2 delete-tags` command in Step 8.4, using that subnet's ID.

#### 9.4 `InsufficientInstanceCapacity` for Dedicated Instances

**Symptom:** A `FailedCreate` event on an AWSMachine contains `api error InsufficientInstanceCapacity: We currently do not have sufficient m5.large capacity in the Availability Zone you requested (us-east-1a).` The machine stays `Provisioned` with no node.

**Cause:** AWS has run out of dedicated hardware for that instance type in the zone of the subnet CAPA chose for the machine.

**Resolution:**

1. List the failed creation events:
   ```bash
   kubectl -n fleet-default get events --field-selector reason=FailedCreate
   ```
   Expected: the `InsufficientInstanceCapacity` message for the affected AWSMachine.

2. Read the CAPA log for the same error:
   ```bash
   kubectl -n capa-system logs deploy/capa-controller-manager | grep InsufficientInstanceCapacity
   ```
   Expected: `unable to create instance` lines with the same error, one for each retry.

3. Wait. CAPA retries the launch by itself, and dedicated `m5.large` machines can retry for three to four minutes and then launch with no help. The error message names the zones that have capacity for the instance type.

4. If the error does not go away, change the `instanceType` of the affected pool in `values.yaml` to a type with capacity, then upgrade the release:
   ```bash
   helm upgrade CLUSTER_NAME capa-dedicated-rke2 -n fleet-default
   ```
   Expected: `STATUS: deployed` and a new `REVISION`. Only the changed pool gets a new template name and new machines.

#### 9.5 Cluster `READY` Says `true` but Rancher Says the Cluster Is Not Ready

**Symptom:** `kubectl -n fleet-default get clusters.provisioning.cattle.io` shows `READY true`, but the Rancher `Ready` condition from Step 6.2 is `"status":"Unknown"`.

**Cause:** The `READY` column of the provisioning Cluster reports ahead of Rancher's own `Ready` condition, and the cluster is not usable until that condition is `True`.

**Resolution:**

1. Check Rancher's `Ready` condition:
   ```bash
   kubectl get clusters.management.cattle.io MGMT_CLUSTER_ID -o jsonpath='{.status.conditions[?(@.type=="Ready")]}'
   ```
   Expected: `"status":"True"` once the cluster is ready.

2. Check that every machine is running:
   ```bash
   kubectl -n fleet-default get machines
   ```
   Expected: three rows with `PHASE Running` and `READY True`.

3. Wait until the condition in item 1 reports `"status":"True"`, then continue with Step 7.

#### 9.6 Cluster Goes from Active Back to Updating with `Waiting for viable init node`

**Symptom:** A cluster that was **Active** shows **Updating** in Rancher with the message `Waiting for viable init node`. The control-plane machine shows `Reconciling` with `Waiting for cluster agent to connect`, and Rancher's cluster condition is `Ready=False` with `Cluster agent is not connected`.

**Cause:** The cluster's EC2 instances were stopped, for example by a scheduled shutdown.

**Resolution:**

1. Check the state of the instances (workstation):
   ```bash
   aws ec2 describe-instance-status --instance-ids INSTANCE_IDS --include-all-instances --query 'InstanceStatuses[].[InstanceId,InstanceState.Name]' --output text
   ```
   Expected: each instance ID followed by `stopped`.

2. Start the instances:
   ```bash
   aws ec2 start-instances --instance-ids INSTANCE_IDS
   ```
   Expected: AWS lists the instances it is starting.

3. Wait about 3 minutes, then check Rancher's `Ready` condition with the command in Step 6.2. Expected: `"status":"True"`. The cluster returns with the same machines.

---

## References

- [CAPA Dedicated Tenancy Cluster Template (source article)](../infra/CAPA_Dedicated_Tenancy_Cluster_Template.md)
- [Cluster API Provider for AWS: Bring Your Own AWS Infrastructure](https://cluster-api-aws.sigs.k8s.io/topics/bring-your-own-aws-infrastructure)
- [Rancher Turtles and Cluster API](../infra/Rancher_Turtles_Cluster_API.md)
- [Configuring Native CAPI Infrastructure Providers to Provision RKE2 Clusters (Rancher v2.15)](https://documentation.suse.com/cloudnative/rancher-manager/v2.15/en/cluster-deployment/configuration/capi-infrastructure-providers.html)
- [Rancher Manager: Native CAPI Infrastructure Providers](https://ranchermanager.docs.rancher.com/how-to-guides/advanced-user-guides/capi-infrastructure-providers)
- [Rancher Turtles documentation](https://turtles.docs.rancher.com/turtles/stable/en/index.html)
- [Rancher Turtles: CAPIProvider reference](https://turtles.docs.rancher.com/turtles/stable/en/reference/capiprovider.html)
- [Cluster API Provider for AWS: multi-tenancy and AWSClusterStaticIdentity](https://cluster-api-aws.sigs.k8s.io/topics/multitenancy)
- [clusterawsadm](https://cluster-api-aws.sigs.k8s.io/clusterawsadm/clusterawsadm)
- [AWS EC2 Dedicated Instances](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/dedicated-instance.html)
- [AWS cloud controller manager chart repository](https://kubernetes.github.io/cloud-provider-aws)
- [Helm: Charts and chart templates](https://helm.sh/docs/topics/charts/)
