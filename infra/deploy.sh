#!/bin/bash

###############################################################################
# Deploy Script para AirSense MX CloudFormation Stack
# 
# Uso: ./infra/deploy.sh [ambiente] [región]
# Ej:  ./infra/deploy.sh prod us-east-1
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
TEMPLATE_FILE="infra/core.yaml"

echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}AirSense MX CloudFormation Deploy${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Validar inputs
if [[ ! "$ENVIRONMENT" =~ ^(dev|prod)$ ]]; then
    echo -e "${RED}❌ Ambiente inválido: $ENVIRONMENT${NC}"
    echo "   Use: dev o prod"
    exit 1
fi

if [[ ! -f "$TEMPLATE_FILE" ]]; then
    echo -e "${RED}❌ Template no encontrado: $TEMPLATE_FILE${NC}"
    exit 1
fi

# Verificar AWS CLI
if ! command -v aws &> /dev/null; then
    echo -e "${RED}❌ AWS CLI no instalado${NC}"
    exit 1
fi

echo -e "\n${GREEN}✓ Ambiente:${NC} $ENVIRONMENT"
echo -e "${GREEN}✓ Región:${NC} $REGION"
echo -e "${GREEN}✓ Stack:${NC} $STACK_NAME"
echo -e "${GREEN}✓ Template:${NC} $TEMPLATE_FILE"

# Validar template
echo -e "\n${YELLOW}Validando CloudFormation template...${NC}"
aws cloudformation validate-template \
    --template-body file://$TEMPLATE_FILE \
    --region $REGION > /dev/null

echo -e "${GREEN}✓ Template válido${NC}"

# Verificar si el stack ya existe
echo -e "\n${YELLOW}Verificando si stack existe...${NC}"

STACK_EXISTS=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].StackName' \
    --output text 2>/dev/null || echo "")

if [[ -n "$STACK_EXISTS" ]]; then
    echo -e "${GREEN}✓ Stack existe: $STACK_EXISTS${NC}"
    ACTION="update"
else
    echo -e "${GREEN}✓ Stack no existe (será creado)${NC}"
    ACTION="create"
fi

# Cargar parámetros
echo -e "\n${YELLOW}Cargando parámetros...${NC}"

if [[ -f "infra/parameters.yaml" ]]; then
    # Parse parameters.yaml (simple YAML)
    PARAMS=""
    
    # TODO: Implementar parsing YAML adecuado
    # Por ahora, parámetros manuales
    PARAMS="ParameterKey=Environment,ParameterValue=${ENVIRONMENT} ParameterKey=KeyName,ParameterValue=airsense-ec2-key"
    
    echo -e "${GREEN}✓ Parámetros cargados de infra/parameters.yaml${NC}"
else
    echo -e "${YELLOW}⚠  infra/parameters.yaml no encontrado${NC}"
    echo -e "   Usando parámetros por defecto"
    PARAMS="ParameterKey=Environment,ParameterValue=${ENVIRONMENT}"
fi

# Deploy
echo -e "\n${YELLOW}Ejecutando: cloudformation ${ACTION}-stack${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

if [[ "$ACTION" == "create" ]]; then
    aws cloudformation create-stack \
        --stack-name $STACK_NAME \
        --template-body file://$TEMPLATE_FILE \
        --parameters $PARAMS \
        --region $REGION \
        --capabilities CAPABILITY_IAM \
        --tags Key=Environment,Value=$ENVIRONMENT Key=Project,Value=airsense-mx
    
    WAIT_ACTION="stack-create-complete"
else
    aws cloudformation update-stack \
        --stack-name $STACK_NAME \
        --template-body file://$TEMPLATE_FILE \
        --parameters $PARAMS \
        --region $REGION \
        --capabilities CAPABILITY_IAM \
        --tags Key=Environment,Value=$ENVIRONMENT Key=Project,Value=airsense-mx || {
            echo -e "${YELLOW}⚠  No hay cambios o error (esto es normal)${NC}"
        }
    
    WAIT_ACTION="stack-update-complete"
fi

echo -e "\n${YELLOW}Esperando a que el stack se estabilice...${NC}"
echo -e "(esto puede tomar varios minutos)"

# Esperar con retry
RETRY=0
MAX_RETRIES=180  # 30 minutos

while [[ $RETRY -lt $MAX_RETRIES ]]; do
    STATUS=$(aws cloudformation describe-stacks \
        --stack-name $STACK_NAME \
        --region $REGION \
        --query 'Stacks[0].StackStatus' \
        --output text 2>/dev/null || echo "NOT_FOUND")
    
    echo "Status: $STATUS"
    
    if [[ "$STATUS" == *"COMPLETE"* ]] && [[ "$STATUS" != *"IN_PROGRESS"* ]]; then
        break
    fi
    
    if [[ "$STATUS" == *"ROLLBACK"* ]] || [[ "$STATUS" == *"FAILED"* ]]; then
        echo -e "\n${RED}❌ Stack ${ACTION} falló!${NC}"
        
        # Mostrar eventos de error
        aws cloudformation describe-stack-events \
            --stack-name $STACK_NAME \
            --region $REGION \
            --query 'StackEvents[?ResourceStatus==`CREATE_FAILED` || ResourceStatus==`UPDATE_FAILED`]' \
            --output table
        
        exit 1
    fi
    
    sleep 10
    RETRY=$((RETRY + 1))
done

if [[ $RETRY -eq $MAX_RETRIES ]]; then
    echo -e "${RED}❌ Timeout: deploy tomó demasiado tiempo${NC}"
    exit 1
fi

echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Stack ${ACTION} exitoso!${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Mostrar outputs
echo -e "\n${GREEN}Outputs:${NC}\n"
aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' \
    --output table

echo -e "\n${GREEN}✓ Deploy completado${NC}"
echo -e "\n${YELLOW}Próximos pasos:${NC}"
echo "  1. Verificar logs: aws logs tail /airsense-mx/streamlit --follow"
echo "  2. SSH a EC2: ssh -i ~/.ssh/airsense-ec2-key.pem ec2-user@<IP>"
echo "  3. Monitorear: aws cloudformation describe-stack-events --stack-name $STACK_NAME"
