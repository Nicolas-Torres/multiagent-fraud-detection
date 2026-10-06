# Enmiendas pendientes — Contrato de Interfaz

**Estado**: 1 enmienda decidida. Vigente: v0.16.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos.
>
> Para recuperar el texto anterior:
>
> ```bash
> git show contrato-v0.16:docs/contrato_de_interfaz.md
> ```

---

## 1. Decididas — listas para redactar

- **§2.5 `Decision` y §7 (persistencia): tres sellos nuevos**, `str | null`:
  `arbiter_prompt_version`, `debate_pro_fraud_prompt_version` y
  `debate_pro_customer_prompt_version`, con la semántica de
  `explanation_prompt_version` (`null` = ningún modelo produjo esa salida). Las
  decisiones anteriores quedan en `null` (ADR-0033). Es aditivo: no cambia ningún
  campo existente.

---

## 2. Abiertas — falta decidir

*(ninguna)*

---

## 3. Hallazgos que **no** tocan el contrato

*(ninguno acumulado todavía en esta versión)*
