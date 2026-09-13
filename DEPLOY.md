# Deploying programming-course

End-to-end procedure to stand up the application in AWS **us-east-1**. Per-stack
parameter tables and cross-stack export names live in
[infra/README.md](infra/README.md).

The internet-facing ALB is the public front door. Its HTTPS:443 listener runs an
`authenticate-cognito` action that challenges every unauthenticated request and
redirects it to the Cognito hosted UI (which federates to Google), then forwards
authenticated traffic to the Next.js static server by default or to the FastAPI
backend for `/api/*`. There is no CloudFront distribution and no SPA S3 bucket;
the SPA runs as its own ECS service.

Everything is CloudFormation-managed and repeatable. This document assumes the
AWS CLI is configured for the target account and Docker is available to build
the two container images.

## Deploy-time parameters / TODO (values you must supply)

| Value | Where it comes from | Used by |
|-------|---------------------|---------|
| `GoogleClientId` | Google Cloud console OAuth 2.0 client | `auth.yaml` |
| `GoogleClientSecret` | Google Cloud console OAuth 2.0 client | `auth.yaml` |
| Cognito domain prefix (`CognitoDomainPrefix`) | You choose a globally-unique prefix | `auth.yaml` |
| `AppUrl` | The fixed public app domain, e.g. `https://programming-course.doronbl.people.aws.dev` | `auth.yaml` (callback/logout URLs) |
| ACM certificate ARN (`CertificateArn`) | An ACM cert in **us-east-1** covering the app domain | `network.yaml` (ALB HTTPS:443 listener) |
| Backend image tag / URI | The image you push to the `course-backend` ECR repo | `compute.yaml` |
| Frontend image tag / URI | The image you push to the `course-frontend` ECR repo | `compute.yaml` |

## Ordered deploy procedure

Deploy with `create-stack` + `aws cloudformation wait` (not `deploy`). Set once:

```sh
REGION=us-east-1
APP_URL=https://programming-course.doronbl.people.aws.dev
CERT=<acm-cert-arn-covering-the-app-domain>
cd infra
```

### 1. Auth (Cognito, Google-only Managed Login)

Creates the user pool, the Google IdP, the Managed Login domain, the public SPA
client, and a confidential ALB app client whose callback is
`<AppUrl>/oauth2/idpresponse` (used by the ALB `authenticate-cognito` action).

```sh
aws cloudformation create-stack --region $REGION \
  --stack-name programming-course-auth --template-body file://auth.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=GoogleClientId,ParameterValue=<google-client-id> \
    ParameterKey=GoogleClientSecret,ParameterValue=<google-client-secret> \
    ParameterKey=CognitoDomainPrefix,ParameterValue=<globally-unique-prefix> \
    ParameterKey=AppUrl,ParameterValue=$APP_URL
aws cloudformation wait stack-create-complete --region $REGION --stack-name programming-course-auth
```

**Google OAuth prerequisite.** In the Google OAuth client, register the Cognito
Managed Login response URL as an authorized redirect URI:

```
https://<CognitoDomainPrefix>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
```

### 2. Network (ALB front door)

The ALB SG admits 443/80 from the internet, HTTP:80 redirects to HTTPS:443, and
the HTTPS:443 listener runs `authenticate-cognito` (default -> frontend target
group; `/api/*` rule -> backend target group). Requires the ACM cert.

```sh
aws cloudformation create-stack --region $REGION \
  --stack-name programming-course-network --template-body file://network.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters ParameterKey=CertificateArn,ParameterValue=$CERT
aws cloudformation wait stack-create-complete --region $REGION --stack-name programming-course-network
```

### 3. Security (WAF) and Storage (content bucket)

```sh
aws cloudformation create-stack --region $REGION \
  --stack-name programming-course-security --template-body file://security.yaml \
  --parameters ParameterKey=NetworkStackName,ParameterValue=programming-course-network
aws cloudformation create-stack --region $REGION \
  --stack-name programming-course-storage --template-body file://storage.yaml
aws cloudformation wait stack-create-complete --region $REGION --stack-name programming-course-security
aws cloudformation wait stack-create-complete --region $REGION --stack-name programming-course-storage
```

### 4. Compute (ECS Fargate SPOT) with a two-phase image bootstrap

The `course-backend` and `course-frontend` ECR repos are created by the compute
stack, but the ECS services need the images to exist before they can start.
Create the stack with both desired counts at `0` to make the repos, push both
images, then update the counts to `1`.

```sh
aws cloudformation create-stack --region $REGION \
  --stack-name programming-course-compute --template-body file://compute.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=NetworkStackName,ParameterValue=programming-course-network \
    ParameterKey=StorageStackName,ParameterValue=programming-course-storage \
    ParameterKey=AuthStackName,ParameterValue=programming-course-auth \
    ParameterKey=DesiredCount,ParameterValue=0 \
    ParameterKey=FrontendDesiredCount,ParameterValue=0
aws cloudformation wait stack-create-complete --region $REGION --stack-name programming-course-compute

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR=$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR

docker build -t course-backend ../backend
docker tag course-backend $ECR/course-backend:latest
docker push $ECR/course-backend:latest

docker build -t course-frontend ../frontend
docker tag course-frontend $ECR/course-frontend:latest
docker push $ECR/course-frontend:latest

aws cloudformation update-stack --region $REGION \
  --stack-name programming-course-compute --template-body file://compute.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=NetworkStackName,ParameterValue=programming-course-network \
    ParameterKey=StorageStackName,ParameterValue=programming-course-storage \
    ParameterKey=AuthStackName,ParameterValue=programming-course-auth \
    ParameterKey=DesiredCount,ParameterValue=1 \
    ParameterKey=FrontendDesiredCount,ParameterValue=1
aws cloudformation wait stack-update-complete --region $REGION --stack-name programming-course-compute
```

The frontend container renders `/config.json` from its environment on start, so
the static export image stays environment-agnostic (see
[frontend/README.md](frontend/README.md)). The backend also validates the
Cognito JWT itself, in addition to the ALB edge auth (defense in depth).

### 5. Point DNS at the ALB

Create an A-alias for the app domain to the ALB DNS name in the public hosted
zone (using the network stack's `AlbDnsName` and `AlbCanonicalHostedZoneId`
exports).

## Front-door authentication

The ALB HTTPS:443 listener is the single public entry point and challenges every
request with Cognito before any content is served:

1. **Edge auth on all paths.** The default listener action and the `/api/*` rule
   both run `authenticate-cognito`. An unauthenticated request receives an
   HTTP 302 to `https://<CognitoDomainPrefix>.auth.us-east-1.amazoncognito.com/oauth2/authorize?...`,
   which federates to Google. This is the DAST-observable auth challenge at the
   front door.
2. **HTTP -> HTTPS.** Port 80 issues a 301 redirect to HTTPS:443 so the challenge
   always happens over TLS.
3. **Backend defense in depth.** After edge auth, `/api/*` requests reach the
   FastAPI backend, which independently verifies the Cognito JWT signature,
   issuer, and expiry against the pool JWKS.
4. **WAF.** A REGIONAL WebACL (common rule set + known bad inputs + rate limit
   keyed on the real client IP) is associated with the ALB.

## Verify

```sh
# Unauthenticated request -> 302 to the Cognito hosted UI (the auth challenge):
curl -sI https://programming-course.doronbl.people.aws.dev/ | grep -i '^location'
# HTTP :80 -> 301 to HTTPS :443:
curl -sI http://programming-course.doronbl.people.aws.dev/ | grep -iE '^HTTP|^location'
```

In a browser, open the app domain: the front door redirects to Cognito Managed
Login, "Continue with Google" completes sign-in, and the SPA then loads and can
call `/api/hello`.

## Cross-references

- Per-stack parameter tables, exports: [infra/README.md](infra/README.md).
- Backend configuration and endpoints: [backend/README.md](backend/README.md).
- Frontend runtime config and container: [frontend/README.md](frontend/README.md).
