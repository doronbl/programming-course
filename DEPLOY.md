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
| CloudFront prefix list (`CloudFrontPrefixListId`) | *Has a default.* AWS-managed prefix list `com.amazonaws.global.cloudfront.origin-facing`; in us-east-1 this is `pl-3b927c52`. See "Front-door hardening" below | `network.yaml` |
| Origin-verify secret (`OriginVerifySecret`) | *Recommended.* A shared secret you generate; passed to both `network.yaml` and `storage.yaml` so the ALB only serves CloudFront traffic | `network.yaml`, `storage.yaml` |
| Backend cert ARN (`BackendCertificateArn`) | *Optional.* Same ACM cert as the network `CertificateArn`; enables HTTPS on the CloudFront-to-ALB hop | `storage.yaml` |

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

Generate a shared origin-verify secret first so the ALB only serves CloudFront
traffic (see "Front-door hardening" below):

```sh
ORIGIN_SECRET=$(openssl rand -hex 32)
echo "OriginVerifySecret=$ORIGIN_SECRET   # reuse this exact value for the storage stack"
```

```sh
aws cloudformation deploy --region $REGION \
  --stack-name programming-course-network \
  --template-file network.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides OriginVerifySecret=$ORIGIN_SECRET

aws cloudformation deploy --region $REGION \
  --stack-name programming-course-security \
  --template-file security.yaml \
  --parameter-overrides NetworkStackName=programming-course-network
```

The network stack defaults `CloudFrontPrefixListId` to `pl-3b927c52` (the
us-east-1 id of `com.amazonaws.global.cloudfront.origin-facing`). Confirm the
current id for your region and override if needed:

```sh
aws ec2 describe-managed-prefix-lists --region $REGION \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text
```

### 2. Storage + CDN

Creates the private content bucket `course-content-<suffix>`, the private SPA
bucket, and the CloudFront distribution (SPA default behavior + `/api/*` to the
ALB with caching disabled). Then capture the `AppUrl` output for the next step.

Pass the same `OriginVerifySecret` used for the network stack so CloudFront
sends the header the ALB requires. Optionally pass `BackendCertificateArn`
(the same ACM cert as the network `CertificateArn`) to encrypt the
CloudFront-to-ALB hop.

```sh
aws cloudformation deploy --region $REGION \
  --stack-name programming-course-storage \
  --template-file storage.yaml \
  --parameter-overrides \
    NetworkStackName=programming-course-network \
    OriginVerifySecret=$ORIGIN_SECRET

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

## Front-door hardening (CloudFront is the only entry point)

The design intent is that CloudFront is the single front door: it serves the
SPA and proxies `/api/*` to the ALB. Two controls keep the ALB from being a
second, open entry point, and a third addresses the in-AWS transport hop.

1. **ALB ingress restricted to CloudFront edge ranges.** The ALB security group
   allows inbound 80/443 only from the AWS-managed prefix list
   `com.amazonaws.global.cloudfront.origin-facing` (`CloudFrontPrefixListId`,
   default `pl-3b927c52` in us-east-1), not `0.0.0.0/0`. Arbitrary internet
   clients cannot reach the ALB directly.

2. **Shared-secret origin header.** When `OriginVerifySecret` is set (recommended),
   CloudFront attaches an `X-Origin-Verify` header on the `/api/*` origin, and the
   ALB listener forwards only requests carrying the matching value, returning
   `403` otherwise. This defends against the small window where a non-CloudFront
   caller happens to originate from within the prefix-list ranges. Use the *same*
   secret value for the network and storage stacks. Rotate by updating both
   stacks. Leaving it empty (default) forwards all traffic, which is only
   appropriate for a throwaway dev deploy.

3. **WAF keys on the real client IP.** The REGIONAL WebACL is associated with the
   ALB, but requests arrive via CloudFront, so the ALB source IP is a CloudFront
   edge address. The rate-based rule therefore uses `AggregateKeyType:
   FORWARDED_IP` reading `X-Forwarded-For` (CloudFront appends the viewer IP), so
   the limit is per end user rather than per edge node.

### Residual risk: CloudFront-to-ALB transport

By default the CloudFront `/api/*` origin connects to the ALB over **HTTP:80**.
The `Authorization: Bearer <jwt>` header therefore crosses the CloudFront-to-ALB
hop **in cleartext inside the AWS network** on the default (no-cert) deploy path.
The viewer-to-CloudFront leg is always HTTPS (`redirect-to-https`), so this is an
internal-hop exposure, not an internet one.

To close it, deploy with a certificate:

- Set `CertificateArn` on the network stack (adds the ALB HTTPS:443 listener).
- Set `BackendCertificateArn` (the same ACM cert) on the storage stack. The
  CloudFront `/api/*` origin then uses `https-only` and the Bearer token is
  encrypted end to end.

The no-cert default path remains deployable for scaffolding/dev; accept the
internal-hop exposure there or supply a certificate for any environment handling
real tokens.

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
