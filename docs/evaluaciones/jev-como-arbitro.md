# Evaluación: ¿puede Jev reemplazar al árbitro?

> Fecha: 2026-10-04. Prueba en sombra: no tocó producción. Datos de producción
> leídos de LangSmith; el código, el árbitro de ese momento (Sonnet 5,
> `arbiter-verdict:1`).

## Conclusión

**No.** Jev confirma el piso igual que Sonnet, es estable y es mucho más rápido y
barato, pero **omitió todas las escaladas**, que son lo único que justifica tener
un árbitro con LLM.

## Qué es Jev

Un modelo de decisión ("System One") de TypeSafe AI, lanzado el 2026-09-15. No
genera texto: recibe un estado y preguntas tipadas (`Choice`, `Score`, `Noul`) y
devuelve una opción con probabilidades calibradas. TypeSafe declara 70–500 ms por
respuesta y USD 0,042 por millón de tokens de entrada, con la salida gratis.

Sus limitaciones declaradas coinciden con la tarea del árbitro: "no es bueno en
tareas de razonamiento (System 2)", "no está entrenado en dominios
especializados" y "no es un modelo generativo". Además, su idioma fuerte es el
inglés, y el árbitro trabaja en español.

## Por qué no como reemplazo directo

ADR-0016 exige que cada desvío del piso deje su razón escrita
(`confidence_rationale`). Jev no produce texto. El diseño que se evaluó fue un
**híbrido**: Jev decide; si confirma el piso, no hace falta justificar; si escala,
Sonnet escribe la razón. Las opciones que recibe Jev son sólo las iguales o más
cautelosas que el piso, así que no puede aflojarlo.

## La prueba

| Conjunto | Casos | Qué mide |
|---|---|---|
| Producción (LangSmith, 30 días) | 108 (89 consultados; los de piso BLOCK no tienen nada que decidir) | Acuerdo en el caso común, y la única escalada real |
| Construidos para escalar | 12 | Agentes de evidencia caídos, cliente sin perfil, argumento fuerte sin evidencia |
| Traducidos al inglés | 10 | Cuánto pierde Jev por el idioma |

Cada caso, 3 veces a Jev.

## Resultados

| Métrica | Resultado |
|---|---|
| Acuerdo cuando Sonnet confirma el piso | **98/98** |
| **Escaladas omitidas** | **8 de 8**: la real y las 7 construidas |
| Escaladas agregadas | 2 (Jev subió el piso por un argumento que afirmaba hechos sin evidencia) |
| Estabilidad entre repeticiones | 100 % |
| Español contra inglés | Sin diferencia en 10 casos |
| Latencia | p50 0,24 s · p99 0,41 s, contra ~3,9 s de Sonnet |
| Costo por llamada | ~USD 0,00004, contra ~USD 0,006 |

En las escaladas que omitió, la probabilidad de escalar que daba Jev estaba entre
0,00 y 0,14: ningún umbral sobre sus probabilidades las recupera.

**Una salvedad sobre los casos construidos:** 4 de ellos usaban una señal de
"cliente sin perfil" más fuerte que la que emite producción (severidad alta, en
vez de media). La conclusión se sostiene sin ellos: Jev omitió también la
escalada real y las 3 por agentes caídos.

## Comparativa con alternativas

| | Sonnet 5 (actual) | Haiku 4.5 | Jev | Kev | Laya |
|---|---|---|---|---|---|
| Justifica en texto | Sí | Sí | No | No | No |
| Le entra la entrada del árbitro (~1 000 tokens, español) | Sí | Sí | Sí (32k) | Sí (8k), **sólo inglés** | **No** (512–1 024 tokens) |
| Acceso | API | API | Cerrado | Abierto (Apache 2.0), misma API que Jev | Abierto (Apache 2.0) |
| Veredicto | Se mantiene | Alternativa simple, sin probar para el árbitro | **Descartado** | Requeriría traducir o ajustar | Descartado |

## Dos hallazgos que salieron de esta prueba

- **Un bug latente en el árbitro de producción:** el razonamiento de Sonnet 5
  cuenta dentro de `max_tokens`, y con el tope de 500 un caso difícil cortaba el
  veredicto. Lo resolvió [ADR-0031](../adr/0031-el-razonamiento-es-explicito-y-el-tope-lo-cubre.md).
- **Las escaladas dependían de casos que se pueden escribir como regla.** Lo
  resolvió [ADR-0032](../adr/0032-con-evidencia-incompleta-el-piso-no-es-approve.md);
  ver también [la consistencia del árbitro](consistencia-del-arbitro.md).

## Sobre versiones

La API de TypeSafe sólo ofrece alias (`jev-latest`, `jev-preview`), pero cada
respuesta informa la versión que corrió (`jev-1.13.0`). Para auditar una decisión,
habría que sellar ese valor, no el alias.

## Fuentes

- [Jev en OpenRouter: documentación](https://openrouter.ai/docs/guides/community/jev)
- [Jev en Cloudflare Workers AI](https://developers.cloudflare.com/ai/models/typesafe/jev/)
- [TypeSafe: SDK de Python](https://docs.typesafe.ai/sdk/python/usage)
- [Lanzamiento de Jev (MarkTechPost)](https://www.marktechpost.com/2026/09/19/typesafe-ai-releases-jev/)
- [Kev 4B en Hugging Face](https://huggingface.co/jaredpalmer/kev-4b)
- [Laya](https://laya-ai.com/)
