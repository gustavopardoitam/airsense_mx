# Infraestructura AWS — AirSense MX

Configuración **Infrastructure as Code** para desplegar AirSense MX en AWS.

Autores: Antonio Esparza · Gustavo Pardo  
Proyecto: Maestría Data Science ITAM, mayo 2026

---

## Descripción

Infraestructura minimalista, escalable y mantenible usando **AWS CloudFormation**. Despliega:

- **EC2 t3.small** — Streamlit app (dashboard, pronóstico, contingencias)
- **Application Load Balancer (ALB)** — Enrutamiento y health checks
- **S3 Data Lake** — bronze/, silver/, gold/ (Parquet + Snappy)
- **AWS Glue** — Catálogo de metadatos (Hive partitioning)
- **Amazon Athena** — Queries SQL sobre Silver/Gold
- **CloudWatch Logs** — Logging centralizado de app + ETL
- **AWS Secrets Manager** — API keys, credenciales
- **Amazon Bedrock** — Claude Haiku v1.0 para NLP
- **AWS Lambda** — Orquestación batch (ETL diario 06:00 AM)
- **EventBridge** — Triggers cron para Lambda

---

## Estructura

```
infra/
├── README.md                  # este archivo
├── core.yaml                  # Stack principal CloudFormation
├── parameters.yaml            # Parámetros de configuración (env-specific)
├── deploy.sh                  # Script de deployment rápido
└── rollback.sh                # Script de rollback
```

---

## Despliegue Rápido

### Requisitos

```bash
aws --version          # AWS CLI v2+
aws sts get-caller-identity  # Verificar credenciales
```

### Deploy (primera vez)

```bash
# 1. Crear parámetros
cat > infra/parameters.yaml << 'EOF'
Environment: prod
VpcId: vpc-xxxxx
SubnetIds: subnet-xxxxx,subnet-yyyyy
EOF

# 2. Validar template
aws cloudformation validate-template \
  --template-body file://infra/core.yaml

# 3. Crear stack
./infra/deploy.sh prod us-east-1

# 4. Esperar a que termine
aws cloudformation wait stack-create-complete \
  --stack-name airsense-mx-prod

# 5. Obtener outputs (URLs, DNS)
aws cloudformation describe-stacks \
  --stack-name airsense-mx-prod \
  --query 'Stacks[0].Outputs[]'
```

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
