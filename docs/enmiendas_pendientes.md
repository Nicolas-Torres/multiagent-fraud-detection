# Enmiendas pendientes — Contrato de Interfaz

**Estado**: ocho enmiendas acumuladas para **v0.8**. Vigente: v0.7.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos.
>
> Para recuperar el texto anterior:
>
> ```bash
> git show contrato-v0.7:docs/contrato_de_interfaz.md
> ```

---

## 1. Decididas — listas para redactar

Las ocho salen de la etapa de inteligencia externa y están respaldadas por
[ADR-0014](adr/0014-la-inteligencia-externa-se-recoge-en-build-y-se-consulta-congelada.md)
y [ADR-0015](adr/0015-la-evidencia-externa-entra-al-veredicto-por-el-vocabulario-del-catalogo.md).

| # | Enmienda | Toca | Por qué |
|---|---|---|---|
| 1 | **`threat_indicators`** entra como tabla trece | §4, §7.1 | Última tabla pendiente del contrato. Dato de gobernanza: mutable, curado por un humano, con audit trail. Misma forma y mismo TTL que `merchant_blacklist`. Con ella §7.1 queda sin pendientes por primera vez desde v0.2. |
| 2 | **`web_search_allowlist`** se especifica como gobernanza **del camino de escritura** | §4 | v0.2 la describía filtrando el fetch en runtime. Con el snapshot de ADR-0014 el enforcement ocurre en el build: lo que no pasa la lista no llega a la base. La lista sigue siendo tabla; cambia dónde se aplica. |
| 3 | `Decision` gana **`threat_intel_version`** | §2.5, §7.1 | Quinto eje de auditoría: con qué generación del snapshot se consultó. `null` no es dato faltante — dice que este veredicto **no consultó inteligencia externa**. Misma semántica que `retrieval_index_version`. |
| 4 | `Transaction` gana **`issuer_bank`** | §2.5, §7.1 | Insumo de FP-10, que pasa a estar vinculada. La columna ya existía en `transactions.csv` y no se modelaba por falta de consumidor. Migración *expand*: nullable, poblada desde el dataset. |
| 5 | §1.2 gana un **cuarto modo de arranque**: `fetch-intel` | §1.2 | La imagen soporta el comando; el CD lo invoca como Job periódico. Misma asimetría que el seed: un fetch fallido deja un snapshot viejo, no un servicio roto. |
| 6 | §1.4 gana **`ANTHROPIC_API_KEY` como insumo del tercer puerto** | §1.4 | Ya estaba declarada para generación; ahora también alimenta `Searcher`. Sigue siendo opcional: sin ella no hay snapshot nuevo, y eso deja la inteligencia externa vacía, no el servicio caído. |
| 7 | §1.4 documenta el **techo organizacional de dominios** | §1.4 | Las restricciones de dominio por request sólo pueden restringir más, nunca expandir la lista configurada a nivel de organización en la Console del proveedor. Es una lista fuera del repo que puede vaciar los resultados sin que nada falle: infraestructura tiene que saber que existe. |
| 8 | §3.3 gana una **cuarta métrica operativa**: antigüedad del snapshot vigente | §3.3 | Un snapshot viejo es citable y silenciosamente obsoleto — el mismo estado legítimo que motivó la métrica de *chunks pendientes de indexar*. |

---

## 2. Abiertas — falta decidir

*(ninguna)*

---

## 3. Hallazgos que **no** tocan el contrato

| Hallazgo | Dónde vive |
|---|---|
| Tercer `Owner` (`THREAT_INTEL`) y el `Input` `indicators` | frontera interna: ADR-0015, acta 07 |
| `discarded_sources` sale del estado del grafo | el rechazo ocurre en el build; queda en el informe del script |
| `merchant_blacklist` y `threat_indicators` son el mismo tipo de objeto | consolidación candidata, entregable 10. No se toca ahora: `merchant_blacklist` alimenta FP-07, que sí está medida |
| `ISSUER_UNDER_ALERT` sin entrada en `SAFE_THEMES` | omisión deliberada; ver ADR-0015 §Consecuencias |
| FP-10 activa y no medida | informe del entregable 7: *"sin ground truth reproducible"*, no recall 0 |
