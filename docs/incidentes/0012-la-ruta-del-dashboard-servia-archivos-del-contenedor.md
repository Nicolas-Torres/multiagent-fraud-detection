# Incidente 0012 — la ruta del dashboard servía archivos del contenedor

**Fecha**: 2026-10-01. **Detectado**: en la revisión de seguridad previa a
publicar las demos. No hubo alerta del sistema ni explotación registrada.
**Impacto potencial**: lectura de cualquier archivo del contenedor por HTTP, sin
autenticación. Incluía el código, el dataset y, en principio,
`/proc/self/environ`, donde viven las claves y la URL de la base.

## Síntoma

En GCP, `GET /..%2F..%2Fpyproject.toml` devolvía `200` con el `pyproject.toml` de
la imagen. En local, `/..%2F..%2F.env` devolvía el `.env`. En Azure, el ingress
normalizó esas variantes y la app recibió la página; el código era el mismo,
así que se trata como vulnerable.

## Causa raíz

El catch-all del SPA (`api/app.py`) servía `DASHBOARD_DIST / full_path` si era
un archivo. `full_path` llega **decodificado**: `%2F` ya es `/`, y `..` no se
resolvía. La ruta sólo se probó con lo que pide el propio dashboard
(`favicon.svg`, rutas profundas como `/cases/{id}`), nunca con una ruta
hostil, y no tenía tests.

## Fix

- `archivo_del_spa(dist, full_path)`: resuelve la ruta y exige que quede dentro
  de `dist/`; si no, `index.html`. También cubre una ruta absoluta.
- `/api/...` inexistente responde `404` JSON en vez de la página con `200`.
- `tests/test_spa_route.py`: la función pura y la ruta por HTTP con
  `..%2F` y `%2e%2e`. Sin el control, los seis casos de recorrido fallan.

## ¿Hubo explotación?

No hay evidencia. Revisado el 2026-10-01:

- **GCP**, logs de Cloud Run de 60 días (más que la retención): los únicos
  pedidos con `..` o `%2F` son las tres pruebas de esta revisión.
- **Azure**, Log Analytics desde el 2026-09-07 (439 mil líneas de acceso):
  ninguno.

Por eso no se rotaron los secretos. Si apareciera evidencia, se rotan los
cinco con `infra/rotate-secrets.sh` (ADR-0023).

## Aprendizaje

Una ruta que sirve archivos desde un parámetro del cliente es una frontera,
aunque la haya escrito uno mismo para el SPA. Se prueba con lo que mandaría un
atacante, no con lo que pide el frontend.
