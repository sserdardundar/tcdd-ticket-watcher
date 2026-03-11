#!/bin/bash
set -e

# ==============================================================================
# Google Cloud Deployment Script for TCDD Ticket Watcher
# ==============================================================================

# Variables (Update these based on your GCP environment)
PROJECT_ID="your-gcp-project-id"
REGION="europe-west1"
REPO_NAME="tcdd-ticket-watcher"

IMAGE_BASE="eu.gcr.io/${PROJECT_ID}/${REPO_NAME}-base:latest"
IMAGE_API="eu.gcr.io/${PROJECT_ID}/${REPO_NAME}-api:latest"
IMAGE_WORKER="eu.gcr.io/${PROJECT_ID}/${REPO_NAME}-worker:latest"

SERVICE_NAME="tcdd-api"
JOB_NAME="tcdd-worker"
SCHEDULER_NAME="tcdd-worker-trigger"

# Secrets (These must be created in Secret Manager beforehand)
# gcloud secrets create telegram-token --data-file=...
# gcloud secrets create admin-token --data-file=...
# gcloud secrets create telegram-webhook-secret --data-file=...
SECRET_TELEGRAM="telegram-token:latest"
SECRET_ADMIN="admin-token:latest"
SECRET_WEBHOOK="telegram-webhook-secret:latest"

echo "1. Building base image via Cloud Build..."
gcloud builds submit --tag ${IMAGE_BASE} -f Dockerfile.base .

echo "2. Building API image (from base)..."
gcloud builds submit --tag ${IMAGE_API} -f Dockerfile.api --build-arg BASE_IMAGE=${IMAGE_BASE} .

echo "3. Building Worker image (from base)..."
gcloud builds submit --tag ${IMAGE_WORKER} -f Dockerfile.worker --build-arg BASE_IMAGE=${IMAGE_BASE} .

echo "4. Deploying API to Cloud Run Service..."
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_API} \
  --region ${REGION} \
  --project ${PROJECT_ID} \
  --allow-unauthenticated \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=${PROJECT_ID} \
  --set-secrets=TELEGRAM_BOT_TOKEN=${SECRET_TELEGRAM},ADMIN_TOKEN=${SECRET_ADMIN},TELEGRAM_WEBHOOK_SECRET=${SECRET_WEBHOOK}

echo "5. Deploying Worker to Cloud Run Jobs..."
gcloud run jobs create ${JOB_NAME} \
  --image ${IMAGE_WORKER} \
  --region ${REGION} \
  --project ${PROJECT_ID} \
  --max-retries 0 \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=${PROJECT_ID} \
  --set-secrets=TELEGRAM_BOT_TOKEN=${SECRET_TELEGRAM},ADMIN_TOKEN=${SECRET_ADMIN},TELEGRAM_WEBHOOK_SECRET=${SECRET_WEBHOOK}

echo "6. Creating Cloud Scheduler to trigger Worker every 5 minutes..."
# Replace with the actual service account email
SERVICE_ACCOUNT="your-compute-sa@developer.gserviceaccount.com"

gcloud scheduler jobs create http ${SCHEDULER_NAME} \
  --location ${REGION} \
  --schedule="*/5 * * * *" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
  --http-method POST \
  --oauth-service-account-email ${SERVICE_ACCOUNT}

echo "Deployment complete. Set the Telegram Webhook URL using:"
echo "curl -X POST https://api.telegram.org/bot<TOKEN>/setWebhook \
  -F \"url=<CLOUD_RUN_URL>/telegram/webhook/<TELEGRAM_WEBHOOK_SECRET>\""
