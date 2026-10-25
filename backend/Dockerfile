# QAR backend: FastAPI app plus the React client build, one image.
# Build context is the repository root (see .dockerignore):
#   docker build -f backend/Dockerfile --target runtime -t qar-backend .
#   docker build -f backend/Dockerfile --target test .        # runs the backend tests
# Secrets are mounted at run time (SECRETS_DIR); none are copied into the image.

FROM node:22.11.0-alpine AS client
WORKDIR /client
COPY client/package.json client/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY client/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bi/roles.json ./roles.json
COPY backend/app ./app
COPY --from=client /client/dist ./static
RUN useradd --system --uid 10001 --no-create-home qar
USER qar
EXPOSE 8766
# One worker: sessions live in process memory (app/auth.py). No access log: it would record
# /callback query strings (the provider's one-time code); app/main.py writes the audit log instead.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8766", "--workers", "1", "--no-server-header", "--no-access-log"]

FROM runtime AS test
USER root
COPY backend/requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements-test.txt
COPY backend/tests ./tests
USER qar
RUN python -m pytest -q -p no:cacheprovider tests
