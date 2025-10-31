# Polymarket Backend — Cloud Deployment Quickstart

This repo contains a one-off script (`fetch_order.py`) and an API service (`main.py`, FastAPI).

## 1) Build container

```bash
# From repo root
docker build -t polymarket-backend:latest .
```

## 2a) Run as a one-off job (Docker)

```bash
docker run --rm \
  --env-file .env \
  polymarket-backend:latest
```

The default container CMD runs:

```bash
python fetch_order.py
```

## 2b) Run API locally (Docker)

```bash
docker run --rm -p 8080:8080 \
  --env-file .env \
  polymarket-backend:latest \
  sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"
```

## 3) Google Cloud Run (recommended)

Prereqs: `gcloud` CLI authenticated, a GCP project selected, and Cloud Run API enabled.

### Build and push image
```bash
PROJECT_ID="$(gcloud config get-value project)"
REGION="us-central1"
IMAGE="gcr.io/$PROJECT_ID/polymarket-backend:latest"

gcloud builds submit --tag "$IMAGE" .
```

### Cloud Run Job (run `fetch_order.py` on-demand or on a schedule)
```bash
gcloud run jobs create polymarket-fetch-order \
  --image "$IMAGE" \
  --region "$REGION" \
  --tasks 1 \
  --set-env-vars CLOB_HOST=https://clob.polymarket.com,CHAIN_ID=137 \
  --set-secrets API_KEY=api-key:latest,API_SECRET=api-secret:latest,API_PASSPHRASE=api-passphrase:latest

# Execute the job
gcloud run jobs execute polymarket-fetch-order --region "$REGION"
```

Tip: Store secrets in Secret Manager and reference them in `--set-secrets` above. If you prefer not to use secrets, replace with `--set-env-vars` (not recommended for sensitive values).

### Cloud Run Service (host the FastAPI)
```bash
gcloud run deploy polymarket-backend \
  --image "$IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars DRY_RUN=true,CHAIN_ID=137,CLOB_HOST=https://clob.polymarket.com \
  --command sh --args -c,"uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"
```

Optional protected endpoints: set `SHEETS_SECRET` and present it as `x-api-key` for mutating routes.

## Environment variables
- Required for `fetch_order.py`: `API_KEY`, `API_SECRET`, `API_PASSPHRASE`
- For trading via API (`/place_order` when `DRY_RUN=false`): `PRIVATE_KEY`, `POLYMARKET_PROXY`
- Useful: `DRY_RUN`, `CLOB_HOST`, `CHAIN_ID`, `SHEETS_SECRET`, `SIGNATURE_TYPE`

Create a local `.env` with your values; the image will read them when you pass `--env-file .env`.
