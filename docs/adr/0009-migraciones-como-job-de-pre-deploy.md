# ADR-0009: las migraciones corren como Job de pre-deploy y son compatibles hacia atrás

- **Estado**: propuesto
- **Fecha**: 2026-08-04

## Contexto

La imagen soporta dos modos de arranque: servir (`uvicorn`) y migrar (`alembic
upgrade head`). El contrato §1.2 propone desde v0.2 que el CD invoque el segundo
como Job de pre-deploy y **no** lo meta en el entrypoint —con N réplicas serían N
migraciones concurrentes—.

Esa parte nunca fue discutida, pero quedó incompleta. Falta lo que ocurre
*alrededor*: con qué artefacto corre el Job, qué pasa si falla, y —lo que menos
se mira— **con qué versión del código tiene que ser compatible el esquema
resultante**.

Ese último punto no es sobre dónde corre la migración sino sobre cómo se escribe.
Durante un rolling update conviven pods de la versión vieja y de la nueva contra
el mismo esquema. Una migración que solo funciona con el código nuevo rompe a los
pods viejos mientras el rollout avanza, y rompe a los nuevos si hay que revertir.

Lleva abierto desde v0.2 —cinco versiones— y es de §1, que valida mi compañero.

## Decisión

El CD ejecuta `alembic upgrade head` como **Job de pre-deploy**, con el **mismo
digest** que va a desplegar, en **una sola instancia**, y **aborta el rollout si
falla**.

Las migraciones se escriben con el patrón *expand / contract*: cada release solo
contiene cambios que la **versión anterior del código tolera**.

- Agregar: columna nullable; el código nuevo la escribe, el viejo la ignora.
- Retirar: backfill y `NOT NULL` en una release; eliminar lo viejo en la
  siguiente.

Corolario operativo: **nunca un `DROP COLUMN` en la misma release que deja de
usar la columna.**

El esquema avanza **solo hacia adelante**. No hay `alembic downgrade` automático
en producción.

La aplicación y el Job de migración usan **el mismo rol de base de datos**.

## Alternativas descartadas

**`alembic upgrade head` en el entrypoint.** Es lo más simple de configurar y
elimina un paso del CD. Se descarta porque con N réplicas hay N procesos
compitiendo por el mismo DDL: en el mejor caso uno gana y los otros esperan
bloqueados; en el peor, dos transacciones se deadlockean y el arranque falla de
forma intermitente e irreproducible.

**initContainer en el Deployment.** Corrige el momento pero no la cardinalidad:
cada pod trae su initContainer, así que el problema de concurrencia vuelve tal
cual.

**Migrar con la última imagen disponible en vez del digest a desplegar.** Migrar
con el código de una versión y ejecutar otra produce desajustes que nadie puede
reproducir después, porque el par (esquema, código) que falló no queda registrado
en ningún lado.

**`alembic downgrade` automático ante un rollback.** Suena simétrico y es
peligroso: un downgrade que elimina una columna **destruye datos** que la versión
anterior tampoco necesitaba, y lo hace justo cuando algo ya salió mal. Con
expand/contract el rollback no necesita tocar el esquema: el código viejo tolera
el esquema nuevo por construcción.

**Dos roles de base de datos** —uno con DDL para migrar, otro solo DML para la
app—. Es la postura correcta en una entidad financiera real: si la aplicación se
compromete, el atacante no puede alterar el esquema. Se descarta **para este
alcance**, no por criterio: obliga a un secreto más que el CD tiene que inyectar
y a mantener permisos por objeto en cada migración nueva. Queda como
recomendación explícita del entregable 10, razonada en el informe.

## Consecuencias

**Se gana** un despliegue en el que el esquema siempre está listo antes de que
llegue tráfico, sin ventanas donde una réplica nueva consulte una columna que aún
no existe; y un rollback que no necesita tocar la base, porque el código anterior
sigue siendo válido contra el esquema nuevo.

**Se paga:**

- **Toda columna nueva nace nullable**, aunque conceptualmente sea obligatoria.
  Las cuatro de scoring y las dos de esta etapa ya entraron así —por instinto,
  ahora por regla—. La nulabilidad real vive en la capa de aplicación hasta que
  llega la release que la hace `NOT NULL`.
- **Retirar algo cuesta dos releases.** Es lento y es tentador saltárselo justo
  cuando el cambio parece inofensivo; ese salto es exactamente lo que rompe un
  rollout en marcha.
- **Un rol único**: si la aplicación se compromete, el atacante tiene DDL. Es una
  simplificación consciente y queda escrita como deuda, no como olvido.
- **El CD gana un paso que puede fallar por su cuenta.** Una migración lenta
  bloquea el despliegue completo, y una que falla lo aborta. Es el
  comportamiento correcto, pero convierte a la base en punto único de fallo del
  pipeline.
- **Forward-only exige disciplina en el diseño**, porque un error de esquema no
  se revierte: se corrige con otra migración hacia adelante, en caliente.
