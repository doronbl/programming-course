# Deploying programming-course

End-to-end procedure to stand up the application in AWS **us-east-1**. This is
the coherent top-level guide; the per-stack parameter tables and cross-stack
export names live in [infra/README.md](infra/README.md) and are not repeated in
full here.

Everything is CloudFormation-managed and repeatable. This document assumes you
have the AWS CLI configured for the target account and Docker available to build
the backend image.

## Deploy-time parameters / TODO (values you must supply)

These cannot be known until deploy time. Gather them first:

| Value | Where it comes from | Used by |
|-------|---------------------|---------|
| `GoogleClientId` | Google Cloud console OAuth 2.0 client | `auth.yaml` |
| `GoogleClientSecret` | Google Cloud console OAuth 2.0 client | `auth.yaml` |
| Cognito domain prefix (`CognitoDomainPrefix`) | You choose a globally-unique prefix, e.g. `programming-course-<something>` | `auth.yaml` |
| `AppUrl` | **Output** of the storage stack (CloudFront domain), or your custom domain | `auth.yaml` (callback/logout URLs) |
| Backend image tag / URI (`BackendImageTag` or `BackendImageUri`) | The image you push to ECR | `compute.yaml` |
| ACM certificate ARN (`CertificateArn`) | *Optional.* An ACM cert in **us-east-1** for a custom domain | `network.yaml`, `storage.yaml` |
| Custom domain (`DomainName`) | *Optional.* CNAME for CloudFront; requires `CertificateArn` | `storage.yaml` |

Ordering caveat worth calling out up front: **`auth` needs `AppUrl`, which is a
storage-stack output.** Deploy storage before auth so its CloudFront `AppUrl`
can be passed to auth (see step 3). If you use a custom domain you already own,
you can supply that as `AppUrl` and relax the ordering.

## Ordered deploy procedure

Set once:

```sh
REGION=us-east-1
cd infra
```

### 1. Network + security

Network first (VPC, subnets, NAT, ALB, target group with `/health:8000`), then
the REGIONAL WAF that associates with the ALB.

```sh
aws cloudformation deploy --region $REGION \
  --stack-name programming-course-network \
  --template-file network.yaml \
  --capabilities CAPABILITY_NAMED_IAM

aws cloudformation deploy --region $REGION \
  --stack-name programming-course-security \
  --template-file security.yaml \
  --parameter-overrides NetworkStackName=programming-course-network
```

### 2. Storage + CDN

Creates the private content bucket `course-content-<suffix>`, the private SPA
bucket, and the CloudFront distribution (SPA default behavior + `/api/*` to the
ALB with caching disabled). Then capture the `AppUrl` output for the next step.

```sh
aws cloudformation deploy --region $REGION \
  --stack-name programming-course-storage \
  --template-file storage.yaml \
  --parameter-overrides NetworkStackName=programming-course-network

APP_URL=$(aws cloudformation describe-stacks --region $REGION \
  --stack-name programming-course-storage \
  --query "Stacks[0].Outputs[?OutputKey=='AppUrl'].OutputValue" --output text)
echo "AppUrl=$APP_URL"
```

### 3. Auth (Cognito, Google-only Managed Login)

Pass the `AppUrl` from step 2 so the callback/logout URLs are correct.

```sh
aws cloudformation deploy --region $REGION \
  --stack-name programming-course-auth \
  --template-file auth.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GoogleClientId=<google-client-id> \
    GoogleClientSecret=<google-client-secret> \
    CognitoDomainPrefix=<globally-unique-prefix> \
    AppUrl=$APP_URL
```

**Google OAuth prerequisite.** In the Google OAuth client, register the Cognito
Managed Login response URL as an authorized redirect URI:

```
https://<CognitoDomainPrefix>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
```

### 4. Push the backend image to ECR

The ECR repository (`course-backend`) is created by the compute stack. On a
first deploy, create the repo, push the image, then deploy the service; on
subsequent deploys just push a new tag and update the service. To create the
repo before pushing, you can deploy compute once with `DesiredCount=0`, or
create the repo out-of-band. Then:

```sh
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REPO_URI=$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/course-backend

aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

docker build -t course-backend ../backend
docker tag course-backend $REPO_URI:latest
docker push $REPO_URI:latest
```

### 5. Deploy compute (ECS Fargate SPOT)

Wires in the network, storage, and auth stacks and runs the service on
FARGATE_SPOT, registered to the ALB target group.

```sh
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

Provide `BackendImageUri=<full-uri>` instead of `BackendImageTag` if you push to
a repository other than the one this stack creates.

### 6. Build and upload the frontend, then invalidate CloudFront

Populate `frontend/public/config.json` from the stack outputs before building
(or upload it alongside the build — it is read at runtime):

- `cognitoDomain` <- auth stack output `CognitoDomainUrl`
- `clientId`      <- auth stack output `UserPoolClientId`
- `region`        <- `us-east-1`
- `apiBase`       <- `/api`

```sh
cd ../frontend
npm ci
npm run build     # produces out/ including index.html and config.json

SPA_BUCKET=$(aws cloudformation describe-stacks --region $REGION \
  --stack-name programming-course-storage \
  --query "Stacks[0].Outputs[?OutputKey=='SpaBucketName'].OutputValue" --output text)
DIST_ID=$(aws cloudformation describe-stacks --region $REGION \
  --stack-name programming-course-storage \
  --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text)

aws s3 sync out/ s3://$SPA_BUCKET/ --delete
aws cloudfront create-invalidation --distribution-id $DIST_ID --paths '/*'
```

## Verify

1. Open the `AppUrl` in a browser. "Login/Register with Google" starts the
   Cognito Managed Login redirect to Google.
2. After returning authenticated, the "Call /hello" button fetches
   `/api/hello` through CloudFront and prints `Hello World`.

## Cross-references

- Per-stack parameter tables, exports, and CloudFront policy ids:
  [infra/README.md](infra/README.md).
- Backend configuration and endpoints: [backend/README.md](backend/README.md).
- Frontend runtime config and PKCE flow: [frontend/README.md](frontend/README.md).
