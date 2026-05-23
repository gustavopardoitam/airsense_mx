# BYOC Runbook — AirSense MX

Guía paso a paso para construir, desplegar y operar la imagen BYOC del modelo
de predicción de calidad del aire en SageMaker.

## Pre-requisitos

- WSL Ubuntu con Docker Desktop integrado
- AWS CLI configurado: `aws configure`
- Permisos IAM en tu cuenta:
  - `ecr:*` (crear/push de imágenes)
  - `sagemaker:CreateTrainingJob`, `sagemaker:CreateTransformJob`
  - `s3:GetObject`, `s3:PutObject` sobre el bucket `airsense-mx`
  - `iam:PassRole` para el rol de ejecución SageMaker

## Verificación inicial

```bash
# Docker corriendo
docker ps

# AWS CLI configurado
aws sts get-caller-identity

# Versión de Docker
docker --version          # >= 20.10
```

---

## Flujo completo: de cero a modelo entrenado

### 1. Construir imagen y subirla a ECR (1 vez por versión)

```bash
cd ~/repos/airsense_mx
chmod +x scripts/build_and_push_ecr.sh
./scripts/build_and_push_ecr.sh v1.0
```

Tiempo estimado: **3-5 minutos** (build ~2 min, push ~2 min según red).

El script crea el repo ECR si no existe e imprime al final el URI completo:
```
123456789012.dkr.ecr.us-east-1.amazonaws.com/airsense-mx:v1.0
```
Guarda este URI, lo necesitas para los pasos siguientes.

### 2. Verificar que el Gold esté en S3

```bash
aws s3 ls s3://airsense-mx/gold/panel_diario/ --recursive
```

Si no está, primero ejecutar el pipeline Silver→Gold (responsabilidad de Antonio
para datos reales, o usar fixture sintética para testing).

### 3. Lanzar Training Job

**Opción A: desde SageMaker Studio JupyterLab** (recomendado, ya tiene rol)

```python
from scripts.sagemaker_launch_training import lanzar_training_job

result = lanzar_training_job(
    image_uri="123456789012.dkr.ecr.us-east-1.amazonaws.com/airsense-mx:v1.0",
    gold_s3_path="s3://airsense-mx/gold/panel_diario.parquet",
    output_s3_path="s3://airsense-mx/models/v1.0/",
    instance_type="ml.m5.large",
    horizonte=1,
)
print(result)
```

**Opción B: desde terminal local** (requiere ARN del rol explícito)

```bash
python scripts/sagemaker_launch_training.py \
    --image-uri 123456789012.dkr.ecr.us-east-1.amazonaws.com/airsense-mx:v1.0 \
    --gold-s3-path s3://airsense-mx/gold/panel_diario.parquet \
    --output-s3-path s3://airsense-mx/models/v1.0/ \
    --role arn:aws:iam::123456789012:role/SageMakerExecutionRole \
    --instance-type ml.m5.large
```

Tiempo estimado: **5-10 minutos** (1-2 min de provisioning + 2-5 min de training).

### 4. Verificar resultado en CloudWatch

El log del job aparece en CloudWatch bajo el log group:
```
/aws/sagemaker/TrainingJobs
```

Busca el log stream con el nombre del job (`airsense-mx-train-h1-...`). Al final
deberías ver:
```
[INFO] RESULTADOS DEL ENTRENAMIENTO
[INFO] O3:   MAE=4.60, baseline=5.72, mejora=+19.6%, paso_baseline=True
[INFO] PM25: MAE=1.60, baseline=1.85, mejora=+13.6%, paso_baseline=True
[INFO] PM10: MAE=3.28, baseline=3.80, mejora=+13.7%, paso_baseline=True
[INFO] ✓ Training completado exitosamente
```

### 5. Localizar el modelo entrenado

SageMaker comprime el contenido de `/opt/ml/model/` en un `model.tar.gz`:
```
s3://airsense-mx/models/v1.0/airsense-mx-train-h1-YYYYMMDD-HHMMSS/output/model.tar.gz
```

Para inspeccionarlo localmente:
```bash
aws s3 cp s3://airsense-mx/models/v1.0/.../output/model.tar.gz /tmp/
mkdir /tmp/model && tar xzf /tmp/model.tar.gz -C /tmp/model
ls /tmp/model/
# o3/h1/model_o3_p10.pkl
# o3/h1/model_o3_median.pkl
# ... etc
```

---

## Inferencia: Batch Transform

Una vez tienes el modelo entrenado, puedes generar predicciones masivas con un
Batch Transform Job:

```python
import sagemaker
from sagemaker.transformer import Transformer

session = sagemaker.Session()
role = sagemaker.get_execution_role()

# Crear el modelo en SageMaker apuntando al artifacto del training job
from sagemaker.model import Model
model = Model(
    image_uri="123456789012.dkr.ecr.us-east-1.amazonaws.com/airsense-mx:v1.0",
    model_data="s3://airsense-mx/models/v1.0/.../output/model.tar.gz",
    role=role,
    name="airsense-mx-v1-0",
    env={
        "HORIZONTE": "1",
        "MODELO_VERSION": "lgbm_v1.0",
    },
)

transformer = model.transformer(
    instance_count=1,
    instance_type="ml.m5.large",
    output_path="s3://airsense-mx/gold/predicciones_diarias/",
    strategy="SingleRecord",  # un parquet de entrada, un parquet de salida
)
transformer.transform(
    data="s3://airsense-mx/gold/panel_diario.parquet",
    content_type="application/x-parquet",
)
transformer.wait()
```

---

## Troubleshooting

### El build de Docker falla con "no space left on device"
```bash
docker system prune -a   # libera espacio de imágenes antiguas
```

### El push a ECR falla con "denied: requested access to the resource is denied"
```bash
# Re-autenticarse contra ECR
aws ecr get-login-password --region us-east-1 \
    | docker login --username AWS \
    --password-stdin "$(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com"
```

### Training job falla con "FileNotFoundError"
Causa común: `gold-s3-path` no apunta a un parquet existente o el bucket no
es accesible por el rol SageMaker. Verifica con:
```bash
aws s3 ls s3://airsense-mx/gold/
```

### Training job termina con "ClientError: No space left on device"
La instancia se quedó sin espacio. Subir a `ml.m5.xlarge` o reducir el periodo
de entrenamiento.

### CloudWatch no muestra logs del entrypoint
Verifica que en `train_entrypoint.py` el logging vaya a `stdout` (ya está
configurado así).

---

## Costos estimados (Free Tier amigable)

| Item | Costo |
|---|---|
| ECR storage (~500 MB imagen) | ~$0.05/mes |
| Training job ml.m5.large × 5 min | ~$0.01 por run |
| Batch transform ml.m5.large × 5 min | ~$0.01 por run |
| S3 storage modelo (~10 MB) | despreciable |
| **Total para todo el proyecto** | **< $1 USD** |

---

## Convenciones del proyecto

- **Tagging de imágenes:** `vMAJOR.MINOR` (v1.0, v1.1, v2.0). NUNCA `latest`.
- **Nombre de jobs:** `airsense-mx-train-h{horizonte}-{timestamp}`.
- **Versión del modelo (en metadata):** coincide con el tag de la imagen.
- **Estructura de S3 para modelos:**
  ```
  s3://airsense-mx/models/v1.0/{job_name}/output/model.tar.gz
  ```
