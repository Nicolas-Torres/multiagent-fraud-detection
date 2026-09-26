# Incidente 0007 — carrera al crear los clientes de los proveedores

**Fecha**: 2026-09-26. **Detectado**: en la prueba de carga previa a publicar
las demos (8 análisis en paralelo por nube). No hubo alerta del sistema.
**Impacto**: 3 de 8 casos en GCP con `internal_policy_rag` degradado; uno de
ellos cambió de veredicto (el escenario "approve" salió `CHALLENGE`). En
producción lo dispara el primer pico de visitas después de un arranque en frío,
que es justo lo que trae una publicación. GCP escala a cero, así que arranca en
frío seguido.

## Síntoma

En GCP, recién arrancado (05:49:39 UTC) y sin corridas previas, tres análisis
lanzados a la vez fallaron en el embedding de la consulta:

```
File ".../retrieval/embeddings.py", line 120, in embed
  resultado = self._cliente().models.embed_content(
httpx.ReadError: [SSL] record layer failure (_ssl.c:2580)
```

En los 6 días de logs anteriores el error no aparece nunca. En Azure, con la
instancia ya caliente, los mismos 8 análisis salieron sin degradaciones.

## Causa raíz

Los cuatro adaptadores de proveedor (`GeminiEmbedder`, `AnthropicJudge`,
`AnthropicNarrator`, `AnthropicSearcher`) crean su cliente de forma perezosa en
el primer uso, sin lock:

```python
if self._client is None:
    self._client = genai.Client(api_key=clave)
return self._client
```

Un solo `GraphContext` por proceso comparte cada adaptador entre todos los
análisis, y las llamadas corren en hilos (`asyncio.to_thread`). Con varios hilos
en el primer uso:

1. Todos ven `_client is None` y cada uno crea su propio cliente.
2. El último pisa a los demás en `self._client`.
3. Los clientes huérfanos pierden su última referencia y el recolector los
   cierra: `genai.Client.__del__` llama a `close()`, que cierra el `httpx.Client`
   **mientras otro hilo todavía tiene un request en vuelo** sobre él.

El SDK de Anthropic cierra su cliente HTTP de la misma forma en `__del__`, así
que los tres adaptadores de Anthropic tienen la misma carrera. En esta prueba no
fallaron, porque sus nodos corren más tarde en el grafo y los hilos llegan menos
sincronizados.

Reproducido en local con 16 hilos sobre un `GeminiEmbedder` compartido en frío:
`RuntimeError: Cannot send a request, as the client has been closed`.

## Fix

Un `threading.Lock` por adaptador alrededor de la creación del cliente, y un
test que lanza varios hilos en frío contra un constructor lento y verifica que
se crea un solo cliente.

## Verificación

*(pendiente: se completa con el PR)*

## Aprendizaje

- **Lo perezoso compartido entre hilos necesita lock.** `asyncio.to_thread`
  vuelve concurrente a código que se escribió pensando en un solo llamador.
- **La primera carga después de un arranque en frío es un caso aparte.** Probar
  con la instancia caliente no la cubre. Para GCP, que escala a cero, es el caso
  normal.
- **La reproducción local agotó la cuota gratuita de embeddings de Gemini** (100
  por minuto por proyecto, compartida con producción) durante un minuto. Una
  prueba que llama al proveedor real se dimensiona contra su cuota antes de
  lanzarla.
