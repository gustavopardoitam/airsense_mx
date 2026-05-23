#!/bin/bash

###############################################################################
# Rollback Script para AirSense MX CloudFormation Stack
#
# Uso: ./infra/rollback.sh [ambiente] [región]
# Ej:  ./infra/rollback.sh prod us-east-1
#
###############################################################################

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Variables
ENVIRONMENT=${1:-dev}
REGION=${2:-us-east-1}
STACK_NAME="airsense-mx-${ENVIRONMENT}"

echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${RED}AirSense MX CloudFormation ROLLBACK${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Validar inputs
if [[ ! "$ENVIRONMENT" =~ ^(dev|prod)$ ]]; then
    echo -e "${RED}❌ Ambiente inválido: $ENVIRONMENT${NC}"
    exit 1
fi

echo -e "\n${GREEN}Ambiente:${NC} $ENVIRONMENT"
echo -e "${GREEN}Región:${NC} $REGION"
echo -e "${GREEN}Stack:${NC} $STACK_NAME"

# Confirmación
echo -e "\n${RED}⚠️  ADVERTENCIA: Esto revertirá el stack a su estado anterior${NC}"
read -p "¿Estás seguro? (sí/no): " CONFIRM

if [[ "$CONFIRM" != "sí" ]] && [[ "$CONFIRM" != "yes" ]]; then
    echo -e "${YELLOW}Cancelado${NC}"
    exit 0
fi

# Verificar si el stack existe
STACK_EXISTS=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].StackName' \
    --output text 2>/dev/null || echo "")

if [[ -z "$STACK_EXISTS" ]]; then
    echo -e "${RED}❌ Stack no existe: $STACK_NAME${NC}"
    exit 1
fi

# Ejecutar cancel-update-stack
echo -e "\n${YELLOW}Cancelando stack update...${NC}"
aws cloudformation cancel-update-stack \
    --stack-name $STACK_NAME \
    --region $REGION || {
        echo -e "${YELLOW}⚠  Update no en progreso (intento continuar)${NC}"
    }

# Esperar
echo -e "\n${YELLOW}Esperando rollback...${NC}"
RETRY=0
MAX_RETRIES=180

while [[ $RETRY -lt $MAX_RETRIES ]]; do
    STATUS=$(aws cloudformation describe-stacks \
        --stack-name $STACK_NAME \
        --region $REGION \
        --query 'Stacks[0].StackStatus' \
        --output text 2>/dev/null || echo "NOT_FOUND")
    
    echo "Status: $STATUS"
    
    if [[ "$STATUS" != *"PROGRESS"* ]]; then
        break
    fi
    
    sleep 10
    RETRY=$((RETRY + 1))
done

echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Rollback completado${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Mostrar status final
echo -e "\n${GREEN}Status final:${NC}\n"
aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].[StackName,StackStatus,LastUpdatedTime]' \
    --output table

echo -e "\n${YELLOW}Próximos pasos:${NC}"
echo "  1. Revisar eventos: aws cloudformation describe-stack-events --stack-name $STACK_NAME"
echo "  2. Verificar aplicación: curl <ALB-DNS>:8501"
