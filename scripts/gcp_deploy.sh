#!/bin/bash
set -e

# ==============================================================================
# Google Cloud Deployment Script for TCDD Ticket Watcher
# ==============================================================================

# Variables (Update these based on your GCP environment)
PROJECT_ID="your-gcp-project-id"
REGION="europe-west1"
REPO_NAME="tcdd-ticket-watcher"

IMAGE_API="eu.gcr.io/${PROJECT_ID}/${REPO_NAME}-api:latest"
IMAGE_WORKER="eu.gcr.io/${PROJECT_ID}/${REPO_NAME}-worker:latest"

SERVICE_NAME="tcdd-api"
JOB_NAME="tcdd-worker"
SCHEDULER_NAME="tcdd-worker-trigger"

# Secrets (These must be created in Secret Manager beforehand)
# gcloud secrets create telegram-token --data-file=...
# gcloud secrets create admin-token --data-file=...
SECRET_TELEGRAM="telegram-token:latest"
SECRET_ADMIN="admin-token:latest"

echo "1. Building images via Google Cloud Build..."
gcloud builds submit --tag ${IMAGE_API} -f Dockerfile.api .
gcloud builds submit --tag ${IMAGE_WORKER} -f Dockerfile.worker .

echo "2. Deploying API to Cloud Run Service..."
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_API} \
  --region ${REGION} \
  --project ${PROJECT_ID} \
  --allow-unauthenticated \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=${PROJECT_ID} \
  --set-secrets=TELEGRAM_BOT_TOKEN=${SECRET_TELEGRAM},ADMIN_TOKEN=${SECRET_ADMIN}

echo "3. Deploying Worker to Cloud Run Jobs..."
gcloud run jobs create ${JOB_NAME} \
  --image ${IMAGE_WORKER} \
  --region ${REGION} \
  --project ${PROJECT_ID} \
  --max-retries 0 \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=${PROJECT_ID} \
  --set-secrets=TELEGRAM_BOT_TOKEN=${SECRET_TELEGRAM},ADMIN_TOKEN=${SECRET_ADMIN}

echo "4. Creating Cloud Scheduler to trigger Worker every 5 minutes..."
# Retrieve the service account used by the job (default compute engine or custom)
# Replace with the actual service account email
SERVICE_ACCOUNT="your-compute-sa@developer.gserviceaccount.com"

gcloud scheduler jobs create http ${SCHEDULER_NAME} \
  --location ${REGION} \
  --schedule="*/5 * * * *" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
  --http-method POST \
  --oauth-service-account-email ${SERVICE_ACCOUNT}

echo "Deployment Instructions Generated. Be sure to configure the Webhook URL using:"
echo "curl -X POST https://api.telegram.org/bot<TOKEN>/setWebhook?url=<CLOUD_RUN_URL>/webhook/<TOKEN>"
