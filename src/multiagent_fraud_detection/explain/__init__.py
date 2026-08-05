"""Explicabilidad: el hecho y la lectura, por caminos distintos.

`explanation_audit` sale de una plantilla determinística; `explanation_customer`
de un LLM, con plantilla de respaldo. La separación no es de estilo:

- El texto de auditoría **es** el registro de la decisión y tiene que ser
  reproducible, o el diff del harness deja de significar algo.
- El texto al cliente **omite** deliberadamente lo que el de auditoría dice:
  explicarle la regla a quien quizás sea el defraudador es entregarle el umbral.

Los dos campos son `str` no nulables en el contrato, así que un caso sin
explicación no es representable: si el proveedor de generación falla, degrada a
plantilla, nunca a vacío.
"""
