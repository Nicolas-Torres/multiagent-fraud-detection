# Enmiendas pendientes — Contrato de Interfaz

**Estado**: 3 enmiendas acumuladas hacia **v0.7**. Vigente: **v0.6**.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos.
>
> Las enmiendas de v0.6 se consolidaron en `contrato_de_interfaz.md` y están
> resumidas en [`CHANGELOG.md`](CHANGELOG.md).

---

## 1. Decididas — listas para redactar

### 1.1 §6 se vacía: sus dos pendientes pasaron a ADR

**Toca**: §6, §1.2, §1.5.

Las dos viñetas que llevaban abiertas desde v0.2 quedaron decididas y
documentadas:

| Pendiente | Resolución |
|---|---|
| Convención de tags | [ADR-0008](adr/0008-el-artefacto-de-hand-off-es-el-digest.md): el CD despliega por **digest**; los tags son etiquetas legibles |
| Migraciones | [ADR-0009](adr/0009-migraciones-como-job-de-pre-deploy.md): Job de pre-deploy, mismo digest, una instancia, **compatible hacia atrás** |

§1.5 pasa de *"tags inmutables: semver + git SHA"* a la tabla de eventos del
ADR-0008, y agrega que **el tag de git es la fuente de verdad de la versión** —
`pyproject.toml` deja de ser autoridad sobre el número.

§1.2 incorpora las condiciones que faltaban: el Job corre con el digest que se va
a desplegar, en una sola instancia, y su falla aborta el rollout.

**Nuevo en §1.2**: *expand / contract*. Toda columna nace nullable; retirar algo
cuesta dos releases; **nunca un `DROP COLUMN` en la misma release que deja de
usarla**. No es una regla sobre dónde corre la migración sino sobre cómo se
escribe, y ya se venía cumpliendo sin nombrarla.

Con esto **§6 queda vacío por primera vez desde v0.2.**

### 1.2 §1 gana un tercer momento de ejecución: el seed

**Toca**: §1.2 (que hoy describe dos modos de arranque).

[ADR-0010](adr/0010-seed-como-job-de-post-deploy.md): el CD ejecuta el seed como
**Job de post-deploy**, con el mismo digest, después de la migración y **sin
`--reset`**.

```
# Modo servir (proceso principal)
uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}

# Modo migrar (Job de PRE-deploy, aborta el rollout si falla)
alembic upgrade head

# Modo sembrar (Job de POST-deploy, idempotente, NO aborta el rollout)
python scripts/seed.py
```

**Por qué la asimetría**: la migración es obligatoria para que la aplicación
arranque; el seed carga datos y el sistema funciona sin ellos. Un seed fallido
deja un dashboard vacío, no un servicio roto.

> ⚠️ `--reset` ejecuta `TRUNCATE ... CASCADE` y **arrastra los casos, decisiones
> y resoluciones humanas** — la evidencia del entregable 8. Es herramienta de
> desarrollo local y del runbook: **no aparece en ningún pipeline.**

### 1.3 §1.5 explicita el acceso a GHCR

**Toca**: §1.5.

El paquete queda **privado** y el CD se autentica con un token con
`read:packages`.

**Por qué se escribe**: GHCR es privado por defecto y el `docker pull` falla con
un error de autenticación que se lee como "la imagen no existe". Es el tipo de
detalle que cuesta una tarde el día del despliegue y treinta segundos ahora.

---

## 2. Abiertas — falta decidir

*(ninguna)*

> Los tres ADR nuevos están en estado **propuesto**. Son de §1, que valida el
> compañero: se publican en v0.7 cuando él acuse recibo, o por decisión por
> defecto si no hay objeción en la fecha acordada.

---

## 3. Hallazgos que **no** tocan el contrato

Van al repaso de etapa. Se anotan acá para no perderlos.

### 3.a — RAG de políticas internas → acta 06

- **Tres tablas de gobernanza comparten forma**: `web_search_allowlist`,
  `fraud_policies` y `policy_bindings` llevan `active`, `added_by`, `added_at` y
  `reason`. Modelarlas juntas es más barato que en tres ramas, y
  `web_search_allowlist` no tiene consumidor hasta el Threat Intel Agent. Decidir
  el alcance al abrir la etapa.

- **Un guard por variable de entorno para `--reset`** sería más seguro que
  confiar en que no aparezca en ningún pipeline. Hoy nada impide ejecutarlo
  contra la nube desde una terminal.
