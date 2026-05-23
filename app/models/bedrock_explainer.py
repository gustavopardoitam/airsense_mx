"""Explicaciones en lenguaje natural vía Amazon Bedrock Claude Haiku.

Genera textos amigables para usuarios no técnicos a partir de los datos
de predicción de calidad del aire. Las credenciales se obtienen del
perfil AWS configurado (~/.aws/credentials), nunca hardcodeadas.
"""

from __future__ import annotations

import json

from app.config import BEDROCK_MAX_TOKENS, BEDROCK_MODEL_ID, BEDROCK_REGION
from utils.logging import get_logger

logger = get_logger(__name__)

# Prompt base en español para el modelo
_PROMPT_SISTEMA = (
    "Eres un asistente de salud ambiental para la Ciudad de México. "
    "Explica la calidad del aire de forma clara y útil para una persona "
    "común, en español mexicano. Usa máximo 3 oraciones. No uses términos "
    "técnicos innecesarios. Si hay riesgo, da una recomendación concreta."
)


def generar_explicacion(
    zona: str,
    semaforo: str,
    contaminante: str,
    valor: float,
    unidad: str,
    probabilidad_contingencia: float,
) -> str:
    """Genera una explicación en lenguaje natural usando Claude Haiku.

    Llama a Amazon Bedrock con el modelo Claude Haiku para producir un
    texto corto y accionable sobre la calidad del aire pronosticada.
    Retorna un mensaje de error amigable si Bedrock no está disponible.

    Args:
        zona: Nombre de la zona ('Noroeste', 'Centro', etc.).
        semaforo: Nivel del semáforo ('verde', 'amarillo', 'naranja', 'rojo').
        contaminante: Nombre del contaminante ('Ozono', 'PM2.5', etc.).
        valor: Valor predicho del contaminante.
        unidad: Unidad del contaminante ('ppb', 'µg/m³').
        probabilidad_contingencia: Probabilidad de contingencia [0, 1].

    Returns:
        Texto explicativo en español, o mensaje de fallback si Bedrock falla.
    """
    prompt = _construir_prompt(
        zona, semaforo, contaminante, valor, unidad, probabilidad_contingencia
    )

    try:
        import boto3  # importación diferida

        cliente = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        cuerpo = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": BEDROCK_MAX_TOKENS,
                "system": _PROMPT_SISTEMA,
                "messages": [{"role": "user", "content": prompt}],
            }
        )
        respuesta = cliente.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=cuerpo,
        )
        datos = json.loads(respuesta["body"].read())
        texto = datos["content"][0]["text"].strip()
        logger.info(
            "Explicación generada con Bedrock",
            extra={"zona": zona, "semaforo": semaforo, "tokens": datos.get("usage")},
        )
        return texto
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "No se pudo consultar Bedrock, usando mensaje de fallback",
            extra={"error": str(exc)},
        )
        return _fallback(semaforo)


def _construir_prompt(
    zona: str,
    semaforo: str,
    contaminante: str,
    valor: float,
    unidad: str,
    prob: float,
) -> str:
    """Construye el prompt de usuario para Claude.

    Args:
        zona: Nombre de la zona.
        semaforo: Nivel del semáforo.
        contaminante: Nombre del contaminante.
        valor: Valor predicho.
        unidad: Unidad de medición.
        prob: Probabilidad de contingencia.

    Returns:
        Texto del prompt.
    """
    nivel_pct = round(prob * 100)
    return (
        f"La zona {zona} tiene calidad del aire '{semaforo}' para mañana. "
        f"El contaminante principal es {contaminante} con un valor predicho "
        f"de {valor:.1f} {unidad}. La probabilidad de contingencia ambiental "
        f"es del {nivel_pct}%. ¿Qué le recomendarías a una persona en esa zona?"
    )


def _fallback(semaforo: str) -> str:
    """Retorna un mensaje estático cuando Bedrock no está disponible.

    Args:
        semaforo: Nivel del semáforo.

    Returns:
        Texto de fallback en español.
    """
    mensajes = {
        "verde": (
            "La calidad del aire se prevé buena. "
            "Puedes realizar actividades al aire libre con normalidad."
        ),
        "amarillo": (
            "La calidad del aire es aceptable. "
            "Si eres parte de un grupo sensible, reduce actividades intensas afuera."
        ),
        "naranja": (
            "Se espera mala calidad del aire. "
            "Evita actividades prolongadas al aire libre y mantén ventanas cerradas."
        ),
        "rojo": (
            "Contingencia ambiental prevista. "
            "Evita salir, especialmente niños, adultos mayores "
            "y personas con enfermedades respiratorias."
        ),
    }
    return mensajes.get(semaforo, "Consulta las autoridades ambientales locales.")
