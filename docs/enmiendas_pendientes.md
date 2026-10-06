# Enmiendas pendientes — Contrato de Interfaz

**Estado**: 2 enmiendas decididas. Vigente: v0.16.

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
- **§1.3 y §2.3: `GET /metrics` existe sólo fuera de producción** (ADR-0034). En
  producción la ruta cae al catch-all del dashboard; lo lee sólo el stack local de
  observabilidad (ADR-0024).

---

## 2. Abiertas — falta decidir

*(ninguna)*

---

## 3. Hallazgos que **no** tocan el contrato

*(ninguno acumulado todavía en esta versión)*
