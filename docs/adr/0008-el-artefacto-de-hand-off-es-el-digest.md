# ADR-0008: el artefacto de hand-off es el digest de la imagen, no el tag

- **Estado**: propuesto
- **Fecha**: 2026-08-04

## Contexto

El reparto con infraestructura está fijado desde v0.2 del contrato: yo construyo
y publico la imagen en GHCR (CI), mi compañero la despliega (CD). *"La costura no
es el código ni los schemas: es la imagen versionada en GHCR."*

Lo que quedó sin cerrar en §1.5 es **cómo se nombra y se referencia** esa imagen.
El contrato dice "tags inmutables: semver + git SHA, nunca `latest`", que fija la
intención pero no la mecánica: qué tags emite cada evento de CI, qué string
concreto recibe el CD, y de dónde sale el número de versión.

Está abierto desde v0.2 —cinco versiones— y bloquea el entregable 5: no se puede
escribir el paso de publicación del workflow sin saber qué produce.

Restricción de fondo: **la decisión es de §1, que valida mi compañero.** Este ADR
no resuelve un problema técnico difícil; existe para que la postura esté escrita
y se pueda objetar o aceptar por omisión.

## Decisión

El CD despliega por **digest** (`ghcr.io/…@sha256:…`). Los tags son etiquetas
legibles para humanos; el digest es la referencia real.

CI publica según el evento:

| Evento | Tags |
|---|---|
| push a `main` | `sha-<7>` |
| tag de git `vX.Y.Z` | `X.Y.Z`, `X.Y`, `sha-<7>` |
| pull request | ninguno |
| nunca | `latest` |

**El tag de git es la fuente de verdad de la versión**; CI la inyecta al
construir. `pyproject.toml` deja de ser autoridad sobre el número.

CI expone el digest como salida del job para que el CD lo consuma sin
transcribirlo a mano.

## Alternativas descartadas

**Desplegar por tag inmutable.** Es lo que decía el contrato y es defendible: los
tags se leen, se tipean y se reconocen en un `kubectl describe`. Se descarta
porque *inmutable* ahí es una **promesa**, no una propiedad: nada impide
reetiquetar `1.2.0` sobre otra imagen, y el registro lo acepta sin chistar. Si la
premisa del hand-off es que el compañero despliega exactamente lo que pasó los
tests, esa garantía tiene que ser del sistema y no de la disciplina. El digest es
direccionamiento por contenido: dos digests iguales son la misma imagen, y no hay
forma de mentir.

**`latest` para el CD.** Descartado desde v0.2. Un despliegue que no puede decir
qué versión corre no se puede auditar ni revertir, y `latest` convierte cualquier
push en un despliegue implícito.

**`pyproject.toml` como fuente de la versión.** Obliga a un commit de bump antes
de cada release, que es un paso que se olvida y que además se puede desincronizar
del tag de git. Publicar y versionar pasan a ser dos actos; con el tag de git son
uno solo.

**Tag por rama** (`main`, `develop`). Es un puntero móvil con otro nombre: tiene
el mismo defecto que `latest` con la apariencia de ser específico.

## Consecuencias

**Se gana** que el compañero despliegue exactamente el artefacto que pasó lint y
tests, garantizado por el registro y no por convención; que publicar una versión
sea un solo acto (`git tag`); y que cualquier despliegue sea rastreable hasta un
commit.

**Se paga:**

- **Legibilidad operativa.** `@sha256:9f2c1a…` no se lee ni se recuerda. Un
  incidente a las tres de la mañana es más incómodo con digests que con `1.2.0`.
  Se mitiga publicando el digest junto al tag en el resumen del job de CI, pero
  la incomodidad queda.
- **El CD necesita leer una salida de CI**, no solo pegar un string. Es
  acoplamiento entre los dos pipelines —chico, pero real— justo en la costura que
  el contrato quería mantener delgada.
- **GHCR es privado por defecto.** El CD necesita credenciales con
  `read:packages`, o el paquete se hace público. No es consecuencia de esta
  decisión: es un requisito que aparece con ella y que conviene descubrir ahora.
- **Los tags dejan de ser suficientes** para reproducir un despliegue. Si alguien
  quiere volver a una versión, necesita el digest de esa versión, no su número.
  Eso obliga a que el CD registre el digest desplegado en algún lado.
