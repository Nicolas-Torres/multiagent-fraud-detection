# Enmiendas pendientes — Contrato de Interfaz

**Estado**: 1 enmienda acumulada, lista para redactar en la próxima versión.
Vigente: v0.10.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos.
>
> Para recuperar el texto anterior:
>
> ```bash
> git show contrato-v0.9:docs/contrato_de_interfaz.md
> ```

---

## 1. Decididas — listas para redactar

### `GET /api/v1/cases/{case_id}/stream` — progreso en vivo por SSE

Implementa la mejora que §5 decisión 3 ya anticipaba ("WebSocket = mejora,
entregable 10") — con SSE en vez de WebSocket; el razonamiento completo en
[ADR-0018](adr/0018-el-progreso-en-vivo-se-transmite-por-sse.md).

- **Método/ruta**: `GET /api/v1/cases/{case_id}/stream`
- **Respuesta**: `text/event-stream`. Eventos `node` (`{"node": "<nombre>"}`,
  uno por nodo del grafo que termina) y `done` (cierre — el caso ya está en
  estado terminal, con o sin haber emitido ningún `node`).
- **No es fuente de verdad**: puramente efímero, en memoria del proceso.
  `GET /cases/{id}` (polling) sigue siendo la única fuente del veredicto —
  esto no cambia §2.3 en absoluto, sólo lo complementa.
- **Sin autenticación**, misma deuda declarada que el resto de los
  endpoints HITL (acta 09 §6.1).

---

## 2. Abiertas — falta decidir

*(ninguna)*

---

## 3. Hallazgos que **no** tocan el contrato

*(ninguno acumulado todavía en esta versión)*
