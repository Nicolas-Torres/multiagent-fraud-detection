# ADR-0010: los datos de demostración se siembran con un Job de post-deploy idempotente

- **Estado**: propuesto
- **Fecha**: 2026-08-04

## Contexto

El sistema no sirve para nada contra una base vacía. Para que el dashboard tenga
una cola, para que el harness pueda correr y para grabar el video del entregable
8, el ambiente desplegado necesita los 1 000 perfiles, las 7 000 transacciones y
la lista negra.

`scripts/seed.py` existe y `docs/runbook_base_nueva.md` documenta el
procedimiento, pero **nadie es dueño de ejecutarlo en la nube**. El contrato
define quién construye, quién despliega y quién migra; no dice quién puebla.

Es distinto de una migración ([ADR-0009](0009-migraciones-como-job-de-pre-deploy.md)):
una migración cambia el **esquema** y es obligatoria para que la aplicación
arranque. El seed carga **datos**, y el sistema funciona sin ellos —solo que no
tiene nada que mostrar—.

Hay un detalle que hace la decisión menos trivial de lo que parece: `seed.py
--reset` ejecuta `TRUNCATE ... CASCADE`, que **arrastra `cases`, `decisions`,
`signals` y `human_resolutions`**. Es el comportamiento correcto para una base
local; sería destructivo en un ambiente donde alguien ya resolvió casos.

## Decisión

El CD ejecuta el seed como **Job de post-deploy**, con el mismo digest que acaba
de desplegar, **después** del Job de migración y **sin `--reset`**.

El Job es idempotente: `seed.py` usa `INSERT ... ON CONFLICT DO UPDATE` sobre
`transactions`, `customer_behaviors` y `merchant_blacklist`. Correrlo N veces deja
el mismo estado y **no toca los casos producidos por el sistema**.

`--reset` queda como herramienta de desarrollo local y del runbook. **No aparece
en ningún pipeline.**

## Alternativas descartadas

**Ejecución manual documentada en el runbook.** Es lo que hay hoy de facto, y
tiene una ventaja real: nadie ejecuta nada destructivo por accidente. Se descarta
porque un paso manual que se hace una vez cada tanto se olvida, y se olvida
justo cuando importa —al levantar el ambiente para grabar la demo—. Además deja
la reproducibilidad del ambiente fuera del pipeline, que es lo contrario de lo
que pide el entregable 5.

**Un endpoint de administración protegido.** Daría un botón en el dashboard y
encajaría con la vista de políticas. Se descarta por costo y por superficie: hay
que autenticarlo, autorizarlo y protegerlo de ejecución concurrente, para un
problema que un Job resuelve sin API. Si mañana hace falta recargar datos sin
desplegar, se reconsidera.

**Meterlo en el Job de migración.** Es tentador porque ya existe. Se descarta
porque mezcla esquema y datos: una migración fallida y un seed fallido tienen
causas y remedios distintos, y una migración que carga 7 000 filas deja de ser
reversible mentalmente. Además el seed no debería abortar un rollout: la
aplicación funciona sin datos.

**Correr `seed.py --reset` en cada despliegue** para garantizar un estado
conocido. Se descarta porque el `CASCADE` borra los casos que el sistema produjo,
incluidas las resoluciones humanas — la evidencia del entregable 8 desaparecería
en el siguiente release. El estado conocido se consigue con idempotencia, no con
tierra arrasada.

## Consecuencias

**Se gana** un ambiente reproducible sin pasos manuales, y una demo que se puede
levantar desde cero corriendo el pipeline.

**Se paga:**

- **7 000 upserts en cada despliegue** para reescribir lo mismo. Es barato pero
  no gratis, y el Job agrega tiempo a cada release. Si molesta, la salida es una
  guarda —saltear si la tabla ya tiene datos—, a costa de que un dataset
  actualizado no se propague solo.
- **Los datos de demostración viven en la imagen.** Los CSV se copian al
  construir, así que el dataset queda atado a la versión desplegada. Es
  consistente con tratar el dataset como artefacto versionado
  ([ADR-0003](0003-dataset-sintetico-como-instrumento-de-evaluacion.md)), pero
  significa que cambiar los datos requiere una imagen nueva.
- **`--reset` sigue existiendo y sigue siendo destructivo.** La protección es que
  no aparece en ningún pipeline; no hay nada en el script que impida a un humano
  ejecutarlo contra la nube. Un guard por variable de entorno sería más seguro y
  queda como mejora.
- **Un Job más que puede fallar.** A diferencia de la migración, su falla **no**
  aborta el rollout: la aplicación funciona sin datos. Eso significa que un seed
  fallido puede pasar inadvertido hasta que alguien abre el dashboard vacío.
