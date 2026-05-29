docker # Build & Publish Guide

This document is for packaging and distributing the Docker image. Keep it private.

---

## Prerequisites

- Docker Desktop installed and running
- Access to your private registry (Docker Hub, ECR, or GHCR)
- You're in the project root directory

---

## 1. Build the image

```bash
docker build -t cloud-to-iac:latest .
```

Tag with a version number alongside `latest` so you can roll back if needed:

```bash
docker build -t cloud-to-iac:1.0.0 -t cloud-to-iac:latest .
```

Verify it built correctly:

```bash
docker images cloud-to-iac
```

Test it locally before pushing:

```bash
docker run --rm cloud-to-iac:latest --help
```

---

## 2. Push to a private registry

Pick one of the options below depending on where you're hosting it.

### Option A — Docker Hub (private repo)

```bash
# Log in
docker login

# Tag for your Docker Hub username
docker tag cloud-to-iac:latest tektribe/cloud-to-iac:latest
docker tag cloud-to-iac:1.0.0 tektribe/cloud-to-iac:1.0.0

# Push
docker push tektribe/cloud-to-iac:latest
docker push tektribe/cloud-to-iac:1.0.0
```

Make sure the repo is set to **Private** in Docker Hub settings before pushing.

---

### Option B — Amazon ECR (private)

```bash
# Authenticate Docker to your ECR registry (replace region and account ID)
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  123456789012.dkr.ecr.us-east-1.amazonaws.com

# Create the repo if it doesn't exist yet
aws ecr create-repository \
  --repository-name cloud-to-iac \
  --region us-east-1

# Tag and push
docker tag cloud-to-iac:latest \
  123456789012.dkr.ecr.us-east-1.amazonaws.com/cloud-to-iac:latest

docker tag cloud-to-iac:1.0.0 \
  123456789012.dkr.ecr.us-east-1.amazonaws.com/cloud-to-iac:1.0.0

docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/cloud-to-iac:latest
docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/cloud-to-iac:1.0.0
```

---

### Option C — GitHub Container Registry (private)

```bash
# Create a personal access token with write:packages scope at
# github.com → Settings → Developer settings → Personal access tokens

# Log in
echo YOUR_PAT | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin

# Tag and push
docker tag cloud-to-iac:latest ghcr.io/tektribe/cloud-to-iac:latest
docker tag cloud-to-iac:1.0.0  ghcr.io/tektribe/cloud-to-iac:1.0.0

docker push ghcr.io/tektribe/cloud-to-iac:latest
docker push ghcr.io/tektribe/cloud-to-iac:1.0.0
```

After pushing, go to the package settings on GitHub and set visibility to **Private**.

---

## 3. Releasing a new version

```bash
# Build with the new version tag
docker build -t cloud-to-iac:1.1.0 -t cloud-to-iac:latest .

# Push both tags so :latest always points to the newest release
docker push tektribe/cloud-to-iac:1.1.0
docker push tektribe/cloud-to-iac:latest
```

Keep a changelog somewhere so you remember what changed between versions.

---

## 4. Sharing access with users

### Docker Hub
Go to the repo → Settings → Collaborators and add their Docker Hub username. They can then `docker pull` it after logging in.

### ECR
Add an IAM policy granting `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, and `ecr:GetDownloadUrlForLayer` to their IAM user or role.

### GHCR
Go to the package settings → Manage access and add their GitHub account.

---

## 5. Revoking access

- **Docker Hub** — remove them from the Collaborators list
- **ECR** — remove or revoke the IAM policy
- **GHCR** — remove them from the package access list

---

## Local test commands

Quick sanity check before publishing:

```bash
# Test with AWS env vars
docker run --rm \
  -e AWS_ACCESS_KEY_ID=your_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret \
  -v $(pwd)/output:/output \
  cloud-to-iac:latest scan --region us-east-1

# Test with mounted AWS credentials file
docker run --rm \
  -v ~/.aws:/root/.aws:ro \
  -v $(pwd)/output:/output \
  cloud-to-iac:latest scan --region us-east-1
```
