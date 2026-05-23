#!/usr/bin/env bash
# =============================================================================
# build_and_push_ecr.sh
# =============================================================================
# Construye la imagen BYOC y la sube al ECR de la cuenta AWS configurada.
# Uso:
#     ./scripts/build_and_push_ecr.sh [tag]
#
# Defaults:
#     tag = "v1.0"
#     region = us-east-1 (override con AWS_REGION env var)
#     repo = airsense-mx (override con ECR_REPO env var)
#
# Pre-requisitos:
#     - Docker corriendo en WSL (Docker Desktop)
#     - AWS CLI configurado con credenciales
#     - Permisos IAM para ecr:* en la cuenta destino
# =============================================================================
 
set -euo pipefail
 
# -----------------------------------------------------------------------------
# Configuración
# -----------------------------------------------------------------------------
TAG="${1:-v1.0}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ECR_REPO="${ECR_REPO:-airsense-mx}"
DOCKERFILE="Dockerfile.training"
 
# Detectar account ID dinámicamente
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"
FULL_TAG="${ECR_URI}:${TAG}"
 
echo "==========================================================="
echo "Build & Push imagen BYOC AirSense MX"
echo "==========================================================="
echo "  Account:    ${AWS_ACCOUNT_ID}"
echo "  Region:     ${AWS_REGION}"
echo "  Repo:       ${ECR_REPO}"
echo "  Tag:        ${TAG}"
echo "  Full URI:   ${FULL_TAG}"
echo "  Dockerfile: ${DOCKERFILE}"
echo "==========================================================="
 
# -----------------------------------------------------------------------------
# Paso 1: Crear repo ECR si no existe (idempotente)
# -----------------------------------------------------------------------------
echo ""
echo "[1/4] Verificando/creando repositorio ECR..."
aws ecr describe-repositories \
    --repository-names "${ECR_REPO}" \
    --region "${AWS_REGION}" \
    >/dev/null 2>&1 \
    || aws ecr create-repository \
        --repository-name "${ECR_REPO}" \
        --region "${AWS_REGION}" \
        --image-scanning-configuration scanOnPush=true \
        --image-tag-mutability MUTABLE
 
echo "✓ Repositorio listo: ${ECR_URI}"
 
# -----------------------------------------------------------------------------
# Paso 2: Build de la imagen
# -----------------------------------------------------------------------------
echo ""
echo "[2/4] Construyendo imagen Docker..."
docker build \
    -f "${DOCKERFILE}" \
    -t "${ECR_REPO}:${TAG}" \
    -t "${FULL_TAG}" \
    .
 
echo "✓ Imagen construida"
 
# -----------------------------------------------------------------------------
# Paso 3: Login a ECR
# -----------------------------------------------------------------------------
echo ""
echo "[3/4] Autenticando con ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
    | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
 
echo "✓ Login exitoso"
 
# -----------------------------------------------------------------------------
# Paso 4: Push de la imagen
# -----------------------------------------------------------------------------
echo ""
echo "[4/4] Pusheando imagen a ECR..."
docker push "${FULL_TAG}"
 
echo ""
echo "==========================================================="
echo "✓ Imagen disponible en ECR:"
echo "  ${FULL_TAG}"
echo "==========================================================="
echo ""
echo "Próximo paso: lanzar training job con"
echo "  python scripts/sagemaker_launch_training.py --image-uri ${FULL_TAG}"