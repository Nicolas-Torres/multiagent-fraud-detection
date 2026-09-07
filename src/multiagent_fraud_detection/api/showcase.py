"""Los 5 casos curados de la vitrina pública, en orden de exhibición.

Única fuente para `scripts/seed_showcase.py` (qué siembra) y para
`GET /api/v1/cases/showcase` (qué expone) — que compartan el mismo
diccionario es lo que evita que el frontend pida el `case_id` de una
transacción que este entorno nunca sembró (docs/reviews/11-ci-cd-azure.md
§2.2/§6.1: antes ese `case_id` vivía horneado en el build del frontend, y
un entorno con una base distinta a la que sembró en local daba 404).
"""

CASOS_VITRINA: dict[str, str] = {
    "T-2579": "Aprobación limpia",
    "T-1809": "Monto y horario inusual (FP-01)",
    "T-4445": "Perfil modificado antes de operar (FP-09)",
    "T-1313": "Cuenta nueva, monto grande (FP-08)",
    "T-5816": "Escalado y resuelto por un analista",
}
