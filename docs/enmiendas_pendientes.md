# Enmiendas pendientes — Contrato de Interfaz

**Estado**: vacío. Vigente: **v0.6**.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos.
>
> Las enmiendas de v0.6 se consolidaron en `contrato_de_interfaz.md` y están
> resumidas en [`CHANGELOG.md`](CHANGELOG.md).

---

## 1. Decididas — listas para redactar

*(ninguna)*

---

## 2. Abiertas — falta decidir

### 2.1 Los dos pendientes de §6 no son decisiones, son confirmaciones

**Migraciones** y **convención de tags** llevan abiertos desde v0.2 —cinco
versiones—. La postura está redactada y argumentada; falta el acuse de recibo del
compañero, porque ambos son de §1, que él valida.

Propuesta: convertirlos en **ADR-0008**, con decisión por defecto si no hay
objeción antes de una fecha. Es bloqueo real del entregable 5: no se puede
escribir el paso de publicación de CI sin saber qué tags emite.

Tres precisiones que agregar antes de mandarla:

- **Compatibilidad hacia atrás de las migraciones.** Durante el rollout conviven
  la imagen vieja y la nueva, así que la migración tiene que funcionar con las
  dos (*expand/contract*). Ya se viene cumpliendo sin nombrarlo.
- **El CD despliega por digest**, no por tag. Un tag se puede mover; un digest no.
- **GHCR es privado por defecto.** El compañero necesita credenciales con
  `read:packages`, o el paquete se hace público.

---

## 3. Hallazgos que **no** tocan el contrato

Van al repaso de etapa. Se anotan acá para no perderlos.

### 3.a — RAG de políticas internas → acta 06

*(vacío por ahora)*
