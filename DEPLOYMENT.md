# Deployment Guide: Google Cloud Run + Neon PostgreSQL

## Overview

**Architecture:**
- **FastAPI app** → [Google Cloud Run](https://cloud.google.com/run) (serverless container, scales to zero)
- **PostgreSQL database** → [Neon](https://neon.tech) (serverless Postgres, permanently free)
- **WattTime API** → external service (credentials passed as environment variables)

**Free tier limits (as of 2025):**
| Service | Free allowance |
|---|---|
| Cloud Run | 2M requests/month, 360K GB-seconds memory, 180K vCPU-seconds |
| Artifact Registry | 0.5 GB storage |
| Neon | 0.5 GB storage, unlimited requests, compute auto-suspends |

> A Google Cloud billing account is required even to use the free tier, but you won't be charged as long as you stay within these limits.

---

## Prerequisites

- **Docker Desktop** — already installed
- **A Google account**
- **A Neon account** — sign up at [neon.tech](https://neon.tech) (free, use Google login)
- **`gcloud` CLI** — install with:
  ```bash
  brew install --cask google-cloud-sdk
  ```

---

## Step 1: Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Note your **Project ID** — you'll use it throughout this guide (it looks like `my-project-123456`)
4. Attach a billing account: **Billing → Link a billing account**

Enable the required APIs:
```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com artifactregistry.googleapis.com
```

---

## Step 2: Neon Database

1. Go to [neon.tech](https://neon.tech) and sign up
2. Click **New Project**, choose a name, and select a **US region** (e.g., US East)
3. Once created, go to **Dashboard → Connection Details**
4. Copy the **connection string** — it looks like:
   ```
   postgresql://user:pass@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
5. Save this — it becomes `DATABASE_URL` in later steps

> The database tables are created automatically when the app first starts.

---

## Step 3: Artifact Registry

Create a Docker image repository in Google Cloud:

```bash
gcloud artifacts repositories create pge2ghg \
  --repository-format=docker \
  --location=us-central1
```

Configure Docker to authenticate with the registry:

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
```

---

## Step 4: Build & Push Docker Image

> **Important:** Use `--platform linux/amd64`. Cloud Run runs on x86_64, so if you're on an Apple Silicon Mac you must cross-compile.

```bash
docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/YOUR_PROJECT_ID/pge2ghg/app:latest \
  .

docker push us-central1-docker.pkg.dev/YOUR_PROJECT_ID/pge2ghg/app:latest
```

Replace `YOUR_PROJECT_ID` with your actual Google Cloud project ID.

---

## Step 5: Deploy to Cloud Run

```bash
gcloud run deploy pge2ghg \
  --image us-central1-docker.pkg.dev/YOUR_PROJECT_ID/pge2ghg/app:latest \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8000 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --set-env-vars "DATABASE_URL=YOUR_NEON_URL,WATTTIME_USER=YOUR_USER,WATTTIME_PASS=YOUR_PASS"
```

Replace the three placeholder values:
- `YOUR_PROJECT_ID` — your Google Cloud project ID
- `YOUR_NEON_URL` — the Neon connection string from Step 2
- `YOUR_USER` / `YOUR_PASS` — your WattTime credentials

After deployment, the command prints a service URL:
```
Service URL: https://pge2ghg-xxxx-uc.a.run.app
```

**Key flags:**
- `--min-instances 0` — scales to zero when idle, keeps usage within the free tier
- `--allow-unauthenticated` — public endpoint, no auth token required to call the API

---

## Step 6: Verify

```bash
curl https://YOUR_SERVICE_URL/health
# → {"status": "ok"}
```

Test the main endpoint with a PG&E export file:
```bash
curl -X POST https://YOUR_SERVICE_URL/process \
  -F "file=@data/your_pge_export.csv"
```

View the interactive API docs:
```
https://YOUR_SERVICE_URL/docs
```

---

## Step 7: Redeploying After Code Changes

Rebuild and push the image, then redeploy:

```bash
docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/YOUR_PROJECT_ID/pge2ghg/app:latest .

docker push us-central1-docker.pkg.dev/YOUR_PROJECT_ID/pge2ghg/app:latest

gcloud run deploy pge2ghg \
  --image us-central1-docker.pkg.dev/YOUR_PROJECT_ID/pge2ghg/app:latest \
  --region us-central1
```

The second `gcloud run deploy` reuses all previously set environment variables and flags.

---

## Notes

**Cold starts:** The first request after a period of inactivity takes ~2–3s (Cloud Run container starting up). Neon also has a ~1s cold start if the database has been idle. Both warm up on the first request and subsequent requests are fast.

**To eliminate cold starts:** Use `--min-instances 1` when deploying. This keeps one container warm at all times. At 512Mi memory and low CPU usage, this consumes roughly 1/720th of the free GB-second budget per hour — still well within free limits.

**Update environment variables without redeploying:**
```bash
gcloud run services update pge2ghg \
  --region us-central1 \
  --set-env-vars KEY=VALUE
```

**View logs:**
```bash
gcloud run services logs read pge2ghg --region us-central1
```
