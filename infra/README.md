# Infraestructura AWS — AirSense MX

Configuración **Infrastructure as Code** para desplegar AirSense MX en AWS.

Autores: Antonio Esparza · Gustavo Pardo  
Proyecto: Maestría Data Science ITAM, mayo 2026

---

## Descripción

Infraestructura minimalista usando **AWS CloudFormation + ECS Fargate**. Despliega:

- **ECS Fargate** — Contenedor Streamlit (sin administrar servidores)
- **Application Load Balancer (ALB)** — Enrutamiento y health checks
- **Amazon ECR** — Registro de imágenes Docker
- **S3 Data Lake** — bronze/, silver/, gold/ (Parquet + Snappy)
- **CloudWatch Logs** — Logging centralizado de app
- **AWS Secrets Manager** — API keys y configuración
- **Amazon Bedrock** — Claude Haiku para explicaciones NLP

---

## Estructura

```
infra/
├── README.md                  # este archivo
├── core.yaml                  # Stack principal CloudFormation
├── parameters.example.yaml    # Parámetros de configuración (template)
├── deploy.sh                  # Script de deployment
├── rollback.sh                # Script de rollback
└── Makefile                   # Comandos útiles
```

---

## Despliegue Completo (paso a paso)

### Requisitos

```bash
aws --version          # AWS CLI v2+
docker --version       # Docker Desktop corriendo
aws sts get-caller-identity  # Verificar credenciales activas
```

---

### Paso 1 — Crear repositorio ECR

```bash
aws ecr create-repository \
    --repository-name airsense-mx \
    --region us-east-1

# Guardar el URI del repositorio
ECR_URI=$(aws ecr describe-repositories \
    --repository-names airsense-mx \
    --region us-east-1 \
    --query "repositories[0].repositoryUri" \
    --output text)

echo "ECR URI: $ECR_URI"
```

---

### Paso 2 — Build de la imagen Docker

```bash
# Desde la raíz del repositorio
docker build --network sagemaker -t "${ECR_URI}:latest" .
```

> Asegúrate de tener un `Dockerfile` en la raíz del proyecto que exponga el puerto 8501 y ejecute `streamlit run app/main.py`.

---

### Paso 3 — Push a ECR

```bash
# Autenticarse con ECR
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "${ECR_URI%%/*}"

# Subir imagen
docker push "${ECR_URI}:latest"
```

---

### Paso 4 — Obtener VPC y Subnets

```bash
# VPC por defecto
VPC_ID=$(aws ec2 describe-vpcs \
    --filters Name=isDefault,Values=true \
    --query 'Vpcs[0].VpcId' \
    --output text)

# Subnets (mínimo 2 en diferentes AZs)
SUBNET_IDS=$(aws ec2 describe-subnets \
    --filters Name=vpc-id,Values=$VPC_ID \
    --query 'Subnets[*].SubnetId' \
    --output text | tr '\t' ',')

echo "VPC: $VPC_ID"
echo "Subnets: $SUBNET_IDS"
```

---

### Paso 5 — Deploy CloudFormation

```bash
aws cloudformation deploy \
  --template-file infra/core.yaml \
  --stack-name airsense-mx \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1 \
  --parameter-overrides \
    VpcId="$VPC_ID" \
    SubnetIds="$SUBNET_IDS" \
    ImageUri="${ECR_URI}:latest" \
  --no-fail-on-empty-changeset
```

---

### Paso 6 — Obtener URL de la app

```bash
aws cloudformation describe-stacks \
  --stack-name airsense-mx \
  --query 'Stacks[0].Outputs[?OutputKey==`AppURL`].OutputValue' \
  --output text
```

La URL tendrá el formato: `http://<alb-dns>.us-east-1.elb.amazonaws.com`

---

## Actualizar la App (re-deploy)

```bash
# 1. Obtener cambios del repositorio
git pull

# 2. Rebuild y push de la imagen
docker build --network sagemaker -t "${ECR_URI}:latest" .
docker push "${ECR_URI}:latest"

# 3. Re-deploy (actualiza ECS con la nueva imagen)
aws cloudformation deploy \
  --template-file infra/core.yaml \
  --stack-name airsense-mx \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1 \
  --parameter-overrides \
    VpcId="$VPC_ID" \
    SubnetIds="$SUBNET_IDS" \
    ImageUri="${ECR_URI}:latest" \
  --no-fail-on-empty-changeset
```

> ECS reemplaza las tareas gradualmente (rolling update) sin downtime.

---

## Archivos Principales

| Archivo | Propósito |
|---------|-----------|
| `core.yaml` | CloudFormation template (EC2, ALB, S3, IAM, etc.) |
| `parameters.yaml` | Parámetros por ambiente (NO versionado) |
| `deploy.sh` | Script Bash para crear/actualizar stack |
| `rollback.sh` | Script para rollback de cambios |

---

## Costos Estimados

| Recurso | Costo/mes |
|---------|-----------|
| EC2 t3.small (730 hrs) | $12 |
| ALB | $7 |
| S3 (100 GB) | $2.30 |
| CloudWatch Logs | $2.50 |
| **Total** | **~$25** |

---

## Referencias

- [CloudFormation Docs](https://docs.aws.amazon.com/cloudformation/)
- [EC2 User Data](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html)
- [Hive Partitioning](https://docs.aws.amazon.com/glue/latest/dg/partition-projection.html)

---

**Status:** 🟡 Inicial (v0.1)  
**Last Updated:** 22 de mayo de 2026
