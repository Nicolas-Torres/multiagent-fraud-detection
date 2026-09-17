# Enmiendas pendientes — Contrato de Interfaz

**Estado**: 1 enmienda acumulada. Vigente: v0.14.

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

---

## 2. Abiertas — falta decidir

*(ninguna)*

---

## 3. Hallazgos que **no** tocan el contrato

*(ninguno acumulado todavía en esta versión)*
