# Fixyee Warranty Platform — Backend

NestJS API + FastAPI ai-service + Postgres + Qdrant + Docling, run together via Docker Compose.
This is the AWS-deployed half of the platform. The frontend lives in a separate repo, deployed to Vercel.

## Local run
1. `cp .env.example .env` and fill in every value.
2. `docker compose up -d`
3. Backend on :3001, ai-service on :8000.

## Production (AWS EC2)
See the deployment runbook for full provisioning steps (IAM, S3, SQS, EC2, Caddy/HTTPS, etc).
