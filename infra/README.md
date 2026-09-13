# programming-course infrastructure (CloudFormation)

All AWS infrastructure for the programming-course app, region **us-east-1**. The
infrastructure is split into logical stacks that wire together through stack
Outputs and `Fn::ImportValue`. Deploy them in the order below.

## Stacks

The internet-facing ALB is the public front door. Its HTTPS:443 listener runs
an `authenticate-cognito` action that challenges every unauthenticated request
and redirects it to the Cognito hosted UI (which federates to Google), then
forwards authenticated traffic to the Next.js static server by default or to
the FastAPI backend for `/api/*`.

| Order | File            | Stack (suggested name)         | Purpose |
|-------|-----------------|--------------------------------|---------|
| 1     | `auth.yaml`     | `programming-course-auth`      | Cognito User Pool, Google identity provider (only IdP), Managed Login v2 domain + branding, public SPA app client (OAuth code flow, PKCE, no secret), and a confidential ALB app client (with secret) for the front-door `authenticate-cognito` action. |
| 2     | `network.yaml`  | `programming-course-network`   | VPC (2 public + 2 private subnets across 2 AZs), IGW, NAT gateway, route tables, internet-facing ALB whose security group admits 443/80 from the internet, HTTP:80 -> HTTPS:443 redirect, HTTPS:443 listener with `authenticate-cognito` default action forwarding to the frontend target group and a `/api/*` rule (also `authenticate-cognito`) forwarding to the backend target group. Backend IP target group health-checks `/health` on port `8000`; frontend IP target group health-checks `/` on port `3000`. |
| 3     | `security.yaml` | `programming-course-security`  | REGIONAL WAFv2 WebACL (common rule set + known bad inputs + rate-based rule) associated with the ALB. |
| 4     | `storage.yaml`  | `programming-course-storage`   | Private S3 content bucket `course-content-<suffix>` used by the backend. |
| 5     | `compute.yaml`  | `programming-course-compute`   | ECR repos `course-backend` + `course-frontend`, ECS cluster (FARGATE + FARGATE_SPOT), backend task definition (port `8000`) and frontend task definition (port `3000`), task/execution IAM roles, per-service SGs, two ECS services on FARGATE_SPOT registered to their ALB target groups, CloudWatch log groups. |

### Ordering notes

- `auth` has no cross-stack imports and provides the Cognito user pool ARN, ALB
  app client id, and domain prefix that the ALB listener needs, so it deploys
  first. Its OAuth callback URLs are built from **AppUrl**, which is the fixed
  public domain (`https://programming-course.doronbl.people.aws.dev`), so it no
  longer depends on any other stack for that value.
- `network` imports the Cognito user pool ARN, ALB app client id, and domain
  prefix from `auth` for the `authenticate-cognito` listener actions.
- `security` imports the ALB ARN from `network`.
- `storage` has no cross-stack imports (it is just the content bucket).
- `compute` imports from `network` (VPC, subnets, ALB SG, both target groups),
  `storage` (content bucket name + ARN), and `auth` (user pool id, SPA client
  id, issuer URL, Cognito domain URL). Deploy it last.

## Deploy-time parameters (values you must supply)

### auth.yaml
| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `ProjectName` | no | `programming-course` | |
| `GoogleClientId` | **yes** | — | OAuth client id from Google Cloud console. |
| `GoogleClientSecret` | **yes** | — | OAuth client secret from Google Cloud console. |
| `CognitoDomainPrefix` | **yes** | — | Globally-unique Managed Login domain prefix. |
| `AppUrl` | **yes** | — | Public app URL served by the ALB (e.g. `https://programming-course.doronbl.people.aws.dev`). Builds OAuth callback/logout URLs for the SPA client and the ALB front-door client (`<AppUrl>/oauth2/idpresponse`). |

### network.yaml
| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `ProjectName` | no | `programming-course` | Resource name/tag prefix. |
| `ContainerPort` | no | `8000` | Backend container port. Must match `compute.yaml`. |
| `FrontendContainerPort` | no | `3000` | Frontend container port. Must match `compute.yaml`. |
| `HealthCheckPath` | no | `/health` | Backend target group health endpoint. |
| `FrontendHealthCheckPath` | no | `/` | Frontend target group health endpoint. |
| `CertificateArn` | **yes** | — | ACM cert (us-east-1) covering the public app domain; terminates TLS on the ALB HTTPS:443 listener. |
| `AuthStackName` | yes* | `programming-course-auth` | Import source for the Cognito user pool ARN, ALB app client id, and domain prefix. |

### security.yaml
| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `ProjectName` | no | `programming-course` | |
| `NetworkStackName` | yes* | `programming-course-network` | Name of the deployed network stack (import source). |
| `RateLimit` | no | `2000` | Requests per 5-minute window, keyed on the real client IP via `X-Forwarded-For` (`AggregateKeyType: FORWARDED_IP`). |

### storage.yaml
| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `ProjectName` | no | `programming-course` | Only the private content bucket lives here now. |

### compute.yaml
| Parameter | Required | Default | Notes |
|-----------|----------|---------|-------|
| `ProjectName` | no | `programming-course` | |
| `NetworkStackName` | yes* | `programming-course-network` | VPC, subnets, ALB SG, both target groups. |
| `StorageStackName` | yes* | `programming-course-storage` | Content bucket name + ARN. |
| `AuthStackName` | yes* | `programming-course-auth` | User pool id, SPA client id, issuer URL, Cognito domain URL. |
| `BackendImageUri` | no | `''` | Full backend image URI. If empty, uses the ECR repo created here with `BackendImageTag`. |
| `BackendImageTag` | no | `latest` | Tag used when `BackendImageUri` is empty. |
| `FrontendImageUri` | no | `''` | Full frontend image URI. If empty, uses the frontend ECR repo created here with `FrontendImageTag`. |
| `FrontendImageTag` | no | `latest` | Tag used when `FrontendImageUri` is empty. |
| `ContainerPort` | no | `8000` | Backend port. Must match `network.yaml`. |
| `FrontendContainerPort` | no | `3000` | Frontend port. Must match `network.yaml`. |
| `DesiredCount` | no | `1` | Running backend task count. |
| `FrontendDesiredCount` | no | `1` | Running frontend task count. |
| `TaskCpu` / `TaskMemory` | no | `256` / `512` | Fargate task size (per service). |
| `LogRetentionInDays` | no | `30` | CloudWatch Logs retention. |

\* Required only in the sense that the default must match the actual deployed
stack name; if you keep the default names there is nothing to change.

## Shared values (must stay consistent across infra, backend, frontend)

- Backend container port: **8000**; frontend container port: **3000**
- Backend health check path: **/health**; frontend health check path: **/**
- ALB API path pattern: **/api/\*** (authenticate-cognito then forward to backend)
- Content bucket name pattern: **course-content-\<suffix\>** (suffix is the
  unique GUID segment of `AWS::StackId`, so the name is repeatable per stack
  and unique across deployments — no hardcoded random string).
- Backend container environment variables (set in `compute.yaml`):
  `COGNITO_USER_POOL_ID`, `COGNITO_REGION` (`us-east-1`), `COGNITO_CLIENT_ID`,
  `COGNITO_ISSUER`, `AWS_REGION` (`us-east-1`), `CONTENT_BUCKET`, `PORT` (`8000`).
- Frontend container environment variables (set in `compute.yaml`, rendered into
  `/config.json` at container start): `COGNITO_DOMAIN` (auth `CognitoDomainUrl`),
  `COGNITO_CLIENT_ID` (auth `UserPoolClientId`, the SPA client), `AWS_REGION`
  (`us-east-1`), `API_BASE` (`/api`), `PORT` (`3000`).

## Cross-stack exports

Each stack exports its outputs as `${AWS::StackName}-<OutputName>`. Downstream
stacks import them by passing the upstream stack name as a parameter
(`NetworkStackName`, `StorageStackName`, `AuthStackName`) and using
`Fn::ImportValue`. Key exports:

- auth: `-UserPoolId`, `-UserPoolArn`, `-UserPoolClientId`,
  `-AlbUserPoolClientId`, `-CognitoDomainPrefix`, `-CognitoDomainUrl`,
  `-IssuerUrl`, `-JwksUrl`.
- network: `-VpcId`, `-PublicSubnetIds`, `-PrivateSubnetIds`,
  `-AlbSecurityGroupId`, `-AlbArn`, `-AlbDnsName`, `-AlbCanonicalHostedZoneId`,
  `-HttpsListenerArn`, `-TargetGroupArn`, `-FrontendTargetGroupArn`,
  `-ContainerPort`, `-FrontendContainerPort`.
- security: `-WebAclArn`, `-WebAclId`.
- storage: `-ContentBucketName`, `-ContentBucketArn`.
- compute: `-EcrRepositoryUri`, `-FrontendEcrRepositoryUri`, `-ClusterName`,
  `-ServiceName`, `-ServiceSecurityGroupId`, `-TaskRoleArn`.

## Example deploy (AWS CLI)

See [../DEPLOY.md](../DEPLOY.md) for the full ordered procedure (including image
build/push and the DNS alias). In brief, using `create-stack` + `wait`:

```sh
REGION=us-east-1
APP_URL=https://programming-course.doronbl.people.aws.dev
CERT=<acm-cert-arn-covering-the-app-domain>   # us-east-1

# 1. Auth (Google-only Managed Login; also creates the ALB front-door client)
aws cloudformation create-stack --region $REGION \
  --stack-name programming-course-auth --template-body file://auth.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=GoogleClientId,ParameterValue=xxxx \
    ParameterKey=GoogleClientSecret,ParameterValue=xxxx \
    ParameterKey=CognitoDomainPrefix,ParameterValue=programming-course-demo \
    ParameterKey=AppUrl,ParameterValue=$APP_URL
aws cloudformation wait stack-create-complete --region $REGION --stack-name programming-course-auth

# 2. Network (ALB front door with authenticate-cognito on HTTPS:443)
aws cloudformation create-stack --region $REGION \
  --stack-name programming-course-network --template-body file://network.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters ParameterKey=CertificateArn,ParameterValue=$CERT
aws cloudformation wait stack-create-complete --region $REGION --stack-name programming-course-network

# 3. Security (WAF) and 4. Storage (content bucket)
aws cloudformation create-stack --region $REGION \
  --stack-name programming-course-security --template-body file://security.yaml \
  --parameters ParameterKey=NetworkStackName,ParameterValue=programming-course-network
aws cloudformation create-stack --region $REGION \
  --stack-name programming-course-storage --template-body file://storage.yaml

# 5. Compute: create with DesiredCount=0 to make the ECR repos, push both
#    images, then update DesiredCount/FrontendDesiredCount to 1.
```

> The Google provider requires the Cognito Managed Login redirect URI
> `https://<CognitoDomainPrefix>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse`
> to be registered as an authorized redirect URI in the Google OAuth client.
