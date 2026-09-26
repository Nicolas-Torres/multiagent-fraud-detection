# Enmiendas pendientes — Contrato de Interfaz

**Estado**: 3 enmiendas acumuladas. Vigente: v0.14.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos.
>
> Para recuperar el texto anterior:
>
> ```bash
> git show contrato-v0.11:docs/contrato_de_interfaz.md
> ```

---

## 1. Decididas — listas para redactar

- **`GET /metrics`** (ADR-0024): endpoint operacional nuevo, expone métricas
  HTTP en formato Prometheus (`prometheus-fastapi-instrumentator`), sin
  autenticación, para scrape del collector de observabilidad (Alloy, sólo
  local por ahora). Agregado ya a las tablas de §1.3 y §2.3 con 🆕; falta
  sólo el bump de versión y el `CHANGELOG.md` al cerrar esta etapa.
  Trae consigo dos variables de entorno nuevas en §1.4:
  `OTEL_EXPORTER_OTLP_ENDPOINT` y `OTEL_SERVICE_NAME`.
- **Techo de la demo pública** (ADR-0025): en producción, `POST /cases` y
  `POST /cases/{case_id}/resolution` pueden responder `429` con el motivo en
  `detail` cuando se supera el techo global (40 ejecuciones por hora y 200 por
  día; 20 resoluciones por hora). `/docs`, `/redoc` y `/openapi.json` no existen
  en producción. Falta reflejarlo en las tablas de respuestas de §2.3 y en la
  lista de endpoints de §1.3.
- **Modelos por llamada** (ADR-0026):
  - La explicación al cliente pasa a `claude-haiku-4-5-20251001`:
    `explanation_prompt_version` cambia de valor.
  - La inteligencia externa pasa a Haiku con prompt de sistema:
    `threat_intel_version` pasa a `claude-haiku-4-5-20251001:issuer-alert:v2`.
    El ejemplo de §2.3 (`claude-sonnet-4-6:issuer-alert:v1`) queda viejo.
  - El fetch pasa a ser semanal.

---

## 2. Abiertas — falta decidir

*(ninguna)*

---

## 3. Hallazgos que **no** tocan el contrato

*(ninguno acumulado todavía en esta versión)*
