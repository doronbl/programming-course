# programming-course infrastructure (CloudFormation)

All AWS infrastructure for the programming-course app, region **us-east-1**. The
infrastructure is split into logical stacks that wire together through stack
Outputs and `Fn::ImportValue`. Deploy them in the order below.

## Stacks

| Order | File            | Stack (suggested name)         | Purpose |
|-------|-----------------|--------------------------------|---------|
| 1     | `network.yaml`  | `programming-course-network`   | VPC (2 public + 2 private subnets across 2 AZs), IGW, NAT gateway, route tables, internet-facing ALB, ALB security group, HTTP:80 listener (optional HTTPS:443), IP target group with health check `/health` on port `8000`. |
| 2     | `security.yaml` | `programming-course-security`  | REGIONAL WAFv2 WebACL (common rule set + known bad inputs + rate-based rule) associated with the ALB. |
| 3     | `auth.yaml`     | `programming-course-auth`      | Cognito User Pool, Google identity provider (only IdP), Managed Login v2 domain + branding, public SPA app client (OAuth code flow, PKCE, no secret). |
| 4     | `storage.yaml`  | `programming-course-storage`   | Private S3 content bucket `course-content-<suffix>`, private SPA hosting bucket, CloudFront distribution (SPA default behavior + `/api/*` -> ALB with caching disabled). |
| 5     | `compute.yaml`  | `programming-course-compute`   | ECR repo `course-backend`, ECS cluster (FARGATE + FARGATE_SPOT), task definition (container port `8000`), task/execution IAM roles, service SG, ECS service on FARGATE_SPOT registered to the ALB target group, CloudWatch log group. |

### Ordering notes

- `security` and `auth` only depend on being able to import the ALB ARN
  (`security`) or nothing cross-stack (`auth`), so both can follow `network`.
- `storage` imports the ALB DNS name from `network` (for the `/api/*` origin).
- `compute` imports from `network` (VPC, subnets, ALB SG, target group),
  `storage` (content bucket name + ARN), and `auth` (user pool id, client id,
  issuer URL). Deploy it last.
- `auth` needs the public **AppUrl** (the CloudFront domain) to build OAuth
  callback/logout URLs. On a first deploy, deploy `storage` first to obtain the
  CloudFront domain from its `AppUrl` output, then deploy `auth` with that value
  (or use a custom domain you already own). The table order above assumes you
  supply `AppUrl` up front; if you do not yet know it, deploy `storage` before
  `auth` and adjust accordingly.

## Deploy-time parameters (values you must supply)

### network.yaml
| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `ProjectName` | no | `programming-course` | Resource name/tag prefix. |
| `ContainerPort` | no | `8000` | Must match `compute.yaml`. |
| `HealthCheckPath` | no | `/health` | Backend health endpoint. |
| `CertificateArn` | no | `''` | Optional ACM cert (us-east-1) to add an HTTPS:443 listener. |

### security.yaml
| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `ProjectName` | no | `programming-course` | |
| `NetworkStackName` | yes* | `programming-course-network` | Name of the deployed network stack (import source). |
| `RateLimit` | no | `2000` | Requests per 5-minute window per IP. |

### auth.yaml
| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `ProjectName` | no | `programming-course` | |
| `GoogleClientId` | **yes** | — | OAuth client id from Google Cloud console. |
| `GoogleClientSecret` | **yes** | — | OAuth client secret from Google Cloud console. |
| `CognitoDomainPrefix` | **yes** | — | Globally-unique Managed Login domain prefix. |
| `AppUrl` | **yes** | — | Public app URL (CloudFront domain or custom domain) for OAuth callbacks. |

### storage.yaml
| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `ProjectName` | no | `programming-course` | |
| `NetworkStackName` | yes* | `programming-course-network` | Import source for the ALB DNS name. |
| `PriceClass` | no | `PriceClass_100` | CloudFront price class. |
| `CertificateArn` | no | `''` | Optional ACM cert (us-east-1) for a custom CloudFront domain. |
| `DomainName` | no | `''` | Optional custom domain (requires `CertificateArn`). |

### compute.yaml
| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `ProjectName` | no | `programming-course` | |
| `NetworkStackName` | yes* | `programming-course-network` | VPC, subnets, ALB SG, target group. |
| `StorageStackName` | yes* | `programming-course-storage` | Content bucket name + ARN. |
| `AuthStackName` | yes* | `programming-course-auth` | User pool id, client id, issuer URL. |
| `BackendImageUri` | no | `''` | Full image URI to run. If empty, uses the ECR repo created here with `BackendImageTag`. |
| `BackendImageTag` | no | `latest` | Tag used when `BackendImageUri` is empty. |
| `ContainerPort` | no | `8000` | Must match `network.yaml`. |
| `DesiredCount` | no | `1` | Running task count. |
| `TaskCpu` / `TaskMemory` | no | `256` / `512` | Fargate task size. |
| `LogRetentionInDays` | no | `30` | CloudWatch Logs retention. |

\* Required only in the sense that the default must match the actual deployed
stack name; if you keep the default names there is nothing to change.

## Shared values (must stay consistent across infra, backend, frontend)

- Container port: **8000**
- ALB health check path: **/health**
- CloudFront API path pattern: **/api/\*** (caching disabled)
- Content bucket name pattern: **course-content-\<suffix\>** (suffix is the
  unique GUID segment of `AWS::StackId`, so the name is repeatable per stack
  and unique across deployments — no hardcoded random string).
- Backend container environment variables (set in `compute.yaml`):
  `COGNITO_USER_POOL_ID`, `COGNITO_REGION` (`us-east-1`), `COGNITO_CLIENT_ID`,
  `COGNITO_ISSUER`, `AWS_REGION` (`us-east-1`), `CONTENT_BUCKET`, `PORT` (`8000`).

## Managed CloudFront policy ids used

- CachingDisabled cache policy: `4135ea2d-6df8-44a3-9df3-4b5a84be39ad` (used on `/api/*`).
- AllViewer origin request policy: `216adef6-5c7f-47e4-b989-5492eeaf6572` (forwards
  all viewer headers incl. `Authorization` + query strings on `/api/*`).
- CachingOptimized cache policy: `658327ea-f89d-4fab-a63d-7e88639e58f6` (default SPA behavior).

## Cross-stack exports

Each stack exports its outputs as `${AWS::StackName}-<OutputName>`. Downstream
stacks import them by passing the upstream stack name as a parameter
(`NetworkStackName`, `StorageStackName`, `AuthStackName`) and using
`Fn::ImportValue`. Key exports:

- network: `-VpcId`, `-PublicSubnetIds`, `-PrivateSubnetIds`,
  `-AlbSecurityGroupId`, `-AlbArn`, `-AlbDnsName`, `-HttpListenerArn`,
  `-TargetGroupArn`, `-ContainerPort`.
- security: `-WebAclArn`, `-WebAclId`.
- auth: `-UserPoolId`, `-UserPoolClientId`, `-CognitoDomainUrl`, `-IssuerUrl`, `-JwksUrl`.
- storage: `-ContentBucketName`, `-ContentBucketArn`, `-SpaBucketName`,
  `-DistributionId`, `-DistributionDomainName`, `-AppUrl`.
- compute: `-EcrRepositoryUri`, `-ClusterName`, `-ServiceName`,
  `-ServiceSecurityGroupId`, `-TaskRoleArn`.

## Example deploy (AWS CLI)

```sh
REGION=us-east-1

# 1. Network
aws cloudformation deploy --region $REGION \
  --stack-name programming-course-network \
  --template-file network.yaml \
  --capabilities CAPABILITY_NAMED_IAM

# 2. Security (WAF)
aws cloudformation deploy --region $REGION \
  --stack-name programming-course-security \
  --template-file security.yaml \
  --parameter-overrides NetworkStackName=programming-course-network

# 3. Storage (get AppUrl from its outputs afterwards)
aws cloudformation deploy --region $REGION \
  --stack-name programming-course-storage \
  --template-file storage.yaml \
  --parameter-overrides NetworkStackName=programming-course-network

APP_URL=$(aws cloudformation describe-stacks --region $REGION \
  --stack-name programming-course-storage \
  --query "Stacks[0].Outputs[?OutputKey=='AppUrl'].OutputValue" --output text)

# 4. Auth (Google-only Managed Login)
aws cloudformation deploy --region $REGION \
  --stack-name programming-course-auth \
  --template-file auth.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GoogleClientId=xxxx \
    GoogleClientSecret=xxxx \
    CognitoDomainPrefix=programming-course-demo \
    AppUrl=$APP_URL

# 5. Compute (build + push image to the ECR repo first, then deploy/update)
aws cloudformation deploy --region $REGION \
  --stack-name programming-course-compute \
  --template-file compute.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    NetworkStackName=programming-course-network \
    StorageStackName=programming-course-storage \
    AuthStackName=programming-course-auth \
    BackendImageTag=latest
```

> The Google provider requires the Cognito Managed Login redirect URI
> `https://<CognitoDomainPrefix>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse`
> to be registered as an authorized redirect URI in the Google OAuth client.
