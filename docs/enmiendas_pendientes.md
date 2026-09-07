# Enmiendas pendientes — Contrato de Interfaz

**Estado**: sin enmiendas acumuladas. Vigente: v0.13.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos.
>
> Para recuperar el texto anterior:
>
> ```bash
> git show contrato-v0.10:docs/contrato_de_interfaz.md
> ```

---

## 1. Decididas — listas para redactar

| # | Enmienda | Toca | Por qué |
|---|---|---|---|
| 1 | 🆕 **`GET /api/v1/cases/showcase`** | §2.3, §2.5 | Resuelve en vivo los `case_id` de los 5 casos curados de la vitrina — nunca hornea un id en el build del frontend, que rompía cada vez que la imagen se desplegaba contra una base distinta de la que corrió el seed (acta 11 §2.2/§6.1) |

---

## 2. Abiertas — falta decidir

*(ninguna)*

---

## 3. Hallazgos que **no** tocan el contrato

*(ninguno acumulado todavía en esta versión)*
