# Deploying the Marketplace Simulator

The simulator is a self-contained Python HTTP server. For dev prototyping
(subscribing, downloading, deploying IDP features without a real AWS
Marketplace listing), you have three options, in ascending complexity:

## 1. Local laptop (fastest)

```bash
cd subscription-features/marketplace-simulator
python -m mp_simulator serve --host 127.0.0.1 --port 9999
```

Your **laptop-hosted IDP stack developers** can run `sam deploy` with
`FeaturePlatformSimulatorEndpoint=http://host.docker.internal:9999` (Docker on
Mac/Win) or plain `http://localhost:9999`. Useful for TDD and integration
tests; **cannot** be reached by Lambdas in AWS.

## 2. Docker (local with persistence)

```bash
docker compose up -d
# → simulator on http://localhost:9999, SQLite persisted in ./data/
```

Same reach as option 1 (local only) but SQLite survives restarts.

## 3. Publicly-reachable HTTPS (needed for Lambdas in AWS)

Lambdas running in AWS **cannot reach `localhost`**. You need a public HTTPS
endpoint. Three realistic ways, pick one:

### a. EC2 instance (recommended for shared dev environments)

```bash
# One-shot: t4g.nano + Docker, binds port 443 with self-signed cert.
# ~$3/month; SQLite persists on EBS.
aws cloudformation deploy \
    --stack-name idp-mp-simulator-dev \
    --template-file scripts/simulator-ec2.yaml \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
        VpcId=vpc-xxx \
        SubnetId=subnet-xxx
# Output: SimulatorEndpoint=https://<ec2-ip>.nip.io
```

Paste the `SimulatorEndpoint` into the main IDP stack's
`FeaturePlatformSimulatorEndpoint` parameter. Add the EC2's security-group
CIDR to the Lambda's egress rules if you're in a VPC.

See `scripts/simulator-ec2.yaml` (Step 1 will add this) for the template.

### b. Cloudflare Tunnel / ngrok (fastest for solo demo)

```bash
# Terminal 1: start simulator locally
python -m mp_simulator serve --port 9999

# Terminal 2: tunnel
cloudflared tunnel --url http://localhost:9999
# → https://xxx.trycloudflare.com
```

Paste the trycloudflare URL into `FeaturePlatformSimulatorEndpoint`. Zero
infrastructure to manage; auth is through obscurity.

### c. ECS Fargate / AWS App Runner (production-like)

Use the `Dockerfile` in this directory. Push to ECR, deploy as App Runner
service or Fargate task. More setup but gets you auto-restart, CloudWatch
logs, and a proper HTTPS endpoint.

## Authentication

The simulator currently accepts **unauthenticated** requests on all routes
— it's a dev tool. For shared dev environments, either:

- Put it behind a CloudFront distribution with a long random path prefix, or
- Front it with API Gateway + IAM auth and use a Lambda-custom-endpoint
  adapter (future work), or
- Rely on security-group isolation (option 3a with a private subnet +
  VPC-attached IDP Lambdas).

**Do not** use this simulator on a publicly-accessible endpoint that hosts
real Marketplace data — spoofed entitlements would let anyone "subscribe"
to your IDP features.

## Which should I use?

| Use case                              | Pick  |
|---------------------------------------|-------|
| Unit tests / pytest e2e              | Local (option 1) |
| Running the IDP stack locally via SAM | Local (option 1 or 2) |
| Dev IDP stack deployed in AWS         | Option 3a (EC2) or 3b (Cloudflare) |
| Demoing to a customer                 | Option 3b (Cloudflare — least infra) |
| CI / ephemeral integration tests      | Option 2 (docker compose) |
