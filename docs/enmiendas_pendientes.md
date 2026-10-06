# Enmiendas pendientes — Contrato de Interfaz

**Estado**: 3 enmiendas decididas. Vigente: v0.15.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos.
>
> Para recuperar el texto anterior:
>
> ```bash
> git show contrato-v0.15:docs/contrato_de_interfaz.md
> ```

---

## 1. Decididas — listas para redactar

- **§1, modo fetch-intel**: "Job semanal, lunes 06:00 UTC" pasa a "Job a demanda,
  sin cron: se corre a mano cuando cambia `SNAPSHOT_VERSION`" (ADR-0029). El
  resto del bloque no cambia.
- **§2.3, techos de la demo**: se quita la frase sobre el cooldown por escenario
  (`LIVE-*`, 5 minutos), que también respondía `429`. Desde ADR-0030 la espera
  entre corridas vive sólo en el navegador; el único `429` de `POST /cases` es el
  techo.
- **§7.3 (guarda 4) y la nota del piso en `Decision` (salida del grafo)**: el piso pasa de
  `prescribed_action(catalog, matched_policies)` a
  `piso_efectivo(catalog, matched_policies, degraded_agents)`, que no es APPROVE
  si cayó un agente que produce señales (ADR-0032).

---

## 2. Abiertas — falta decidir

*(ninguna)*

---

## 3. Hallazgos que **no** tocan el contrato

*(ninguno acumulado todavía en esta versión)*
