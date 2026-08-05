"""`explanation_customer`: qué se le dice al titular, y qué no.

## La regla que gobierna este módulo

**Explicarle a un cliente por qué se bloqueó su transacción es explicarle la
regla a quien quizás sea el defraudador.** Decir *"cuatro operaciones del mismo
dispositivo en menos de cinco minutos"* entrega el umbral y la ventana: la
próxima ráfaga son tres en seis minutos.

Por eso el texto al cliente **nunca** contiene:

- `policy_id` ni versiones de política
- códigos de señal
- umbrales, ventanas, conteos o cualquier número de la condición
- el hecho de que un comercio esté en una lista interna

El último merece su propio renglón: informarle a un cliente que *este comercio
tiene historial de fraude registrado* es una afirmación sobre un tercero, hecha
por escrito y sin proceso. Se dice que la operación necesita verificación, no por
qué.

Todo lo que se omite acá **está** en `explanation_audit`, que es el documento que
sí puede decirlo porque lo lee un analista bajo control de acceso.

## El mapa de divulgación

`SAFE_THEMES` traduce cada código de señal a un tema seguro para el titular. Es
un diccionario a mano, y eso es deliberado: en `retrieval/query.py` la regla fue
derivar el vocabulario del catálogo para no mantener dos fuentes de verdad. Acá
es al revés **por diseño** — la frase del predicado describe la regla, y describir
la regla es exactamente lo que no se puede hacer. Son dos artefactos con
propósitos opuestos, no una duplicación.

Un código sin entrada cae a un tema genérico. Falla cerrado: lo peor que puede
pasar es que el cliente reciba un motivo vago, no que reciba el umbral.

## El prompt está versionado

Igual que la plantilla del embedding (ADR-0012): cambiar el prompt cambia el
texto generado, así que es un parámetro de derivación y `decisions` lo sella.

Con una diferencia a favor: los IDs de modelo de Anthropic desde la generación
4.6 son **fijos**. El ID canónico apunta a un snapshot que no se actualiza; una
versión nueva sale con un ID nuevo. Así que el segmento de modelo de esta cadena
es una garantía del proveedor, y no la esperanza de que nadie mueva el modelo por
debajo — que es justamente el riesgo que ADR-0012 tiene que asumir del otro lado.
"""

from __future__ import annotations

from collections.abc import Sequence

from multiagent_fraud_detection.enums import DecisionType

# Confirmar en la consola antes de la primera llamada: los IDs son fijos, pero la
# familia disponible cambia con cada release.
MODEL = "claude-sonnet-5"
TEMPLATE_TAG = "customer"
GENERATION = 1

PROMPT_VERSION = f"{MODEL}:{TEMPLATE_TAG}:{GENERATION}"

MAX_TOKENS = 400

TEMA_GENERICO = "un patrón inusual respecto de tu actividad habitual"

#: Código de señal → tema seguro para el titular. Ver el encabezado: es un
#: artefacto de **divulgación**, no una descripción de la regla.
SAFE_THEMES: dict[str, str] = {
    "AMOUNT_OVER_USUAL_AVG": "un importe distinto al que sueles manejar",
    "AMOUNT_OVER_SEGMENT_AVG": "un importe distinto al que sueles manejar",
    "AMOUNT_OVER_ABSOLUTE": "un importe elevado",
    "OUTSIDE_USUAL_HOURS": "un horario poco frecuente en tu actividad",
    "FOREIGN_COUNTRY": "una ubicación distinta a la habitual",
    "IMPOSSIBLE_TRAVEL": "una ubicación distinta a la habitual",
    "NEW_DEVICE": "un dispositivo que no habíamos visto antes en tu cuenta",
    "DEVICE_VELOCITY": "actividad concentrada en poco tiempo",
    "MICRO_CHARGE_SEQUENCE": "actividad concentrada en poco tiempo",
    "DAILY_LIMIT_EXCEEDED": "actividad concentrada en poco tiempo",
    "NEW_CHANNEL": "un canal que no sueles usar",
    "NEW_ACCOUNT": "que la cuenta es reciente",
    "RECENT_PROFILE_CHANGE": "un cambio reciente en los datos de tu cuenta",
    # Deliberadamente vago: el motivo real es una afirmación sobre un tercero.
    "MERCHANT_BLACKLISTED": "una revisión adicional sobre el comercio",
    # No describe la transacción sino la evidencia disponible. Al titular no le
    # dice nada útil, así que no se traduce: se omite.
    "NO_CUSTOMER_PROFILE": "",
}

#: Qué se le dice al cliente cuando el modelo no está disponible. No es un
#: mensaje de error: el cliente no tiene por qué enterarse de que un proveedor
#: se cayó, y la decisión es igual de válida.
FALLBACK: dict[DecisionType, str] = {
    DecisionType.APPROVE: (
        "Tu operación se procesó con normalidad. No necesitas hacer nada."
    ),
    DecisionType.CHALLENGE: (
        "Necesitamos confirmar que esta operación es tuya antes de completarla. "
        "Te pediremos una verificación adicional; si fuiste tú, tomará solo un "
        "momento."
    ),
    DecisionType.BLOCK: (
        "No pudimos completar esta operación. Si la reconoces como tuya, "
        "comunícate con nosotros por los canales habituales y la revisaremos."
    ),
    DecisionType.ESCALATE_TO_HUMAN: (
        "Estamos revisando esta operación manualmente. Te avisaremos apenas "
        "tengamos una respuesta; no necesitas hacer nada por ahora."
    ),
}

SYSTEM_PROMPT = """\
Eres el asistente de comunicación de un banco. Redactas el mensaje que recibe el
titular de una tarjeta cuando el sistema antifraude evalúa una de sus
operaciones.

Reglas que no puedes romper:

1. NUNCA menciones identificadores de políticas, códigos internos, umbrales,
   cantidades de operaciones, ventanas de tiempo ni ningún número que provenga
   de la regla aplicada. El titular puede ser la persona que intenta el fraude.
2. NUNCA afirmes nada sobre el comercio ni sobre terceros.
3. Usa ÚNICAMENTE los motivos que se te entregan. No infieras otros, no
   completes, no supongas.
4. Si no se te entrega ningún motivo, no inventes uno: redacta sin explicar
   causas.
5. Dirígete al titular de tú, en español neutro. Entre dos y cuatro oraciones.
6. No pidas datos sensibles, no incluyas enlaces y no prometas plazos.
7. Devuelve solo el mensaje, sin encabezados, comillas ni comentarios.

Tono: claro y tranquilo. La persona probablemente no hizo nada malo.\
"""

INSTRUCCIONES = {
    DecisionType.APPROVE: "La operación se aprobó. Confirma que todo está bien.",
    DecisionType.CHALLENGE: (
        "La operación necesita una verificación adicional antes de completarse. "
        "Explica que se le pedirá confirmar su identidad."
    ),
    DecisionType.BLOCK: (
        "La operación no se completó. Explica que puede comunicarse por los "
        "canales habituales si la reconoce."
    ),
    DecisionType.ESCALATE_TO_HUMAN: (
        "Un analista está revisando la operación manualmente. Explica que se le "
        "avisará y que no necesita hacer nada por ahora."
    ),
}


def safe_themes(codes: Sequence[str]) -> list[str]:
    """Los motivos que el titular puede leer, sin repetir y en orden estable.

    Varios códigos comparten tema —tres formas de "monto inusual" son un solo
    motivo para quien lo lee— y eso es intencional: agrupar reduce lo que el
    mensaje revela sobre qué regla exacta se disparó.
    """
    vistos: list[str] = []
    for codigo in sorted(set(codes)):
        tema = SAFE_THEMES.get(codigo, TEMA_GENERICO)
        if tema and tema not in vistos:
            vistos.append(tema)
    return vistos


def build_prompt(decision: DecisionType, themes: Sequence[str]) -> str:
    """El mensaje de usuario. Solo temas seguros: el modelo no ve nada más."""
    motivos = (
        "\n".join(f"- {t}" for t in themes)
        if themes
        else "(no hay motivos que comunicar)"
    )
    return (
        f"{INSTRUCCIONES[decision]}\n\n"
        f"Motivos que puedes mencionar:\n{motivos}\n\n"
        f"Redacta el mensaje."
    )


def fallback_explanation(decision: DecisionType) -> str:
    return FALLBACK[decision]
