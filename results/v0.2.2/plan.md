# Pre-registro de la v0.2.2: comparación con RxNav

Escrito y commiteado **antes** de evaluar RxNav en test2. Los cambios van en "Enmiendas y
desviaciones", con la misma regla de la v0.2.0 (`results/v0.2.0/plan.md`).

- Punto de partida: commit `884063e` (etiqueta `v0.2.1`). No cambian los modelos del benchmark ni
  las reglas de umbral.
- Pregunta: ¿cómo rinde la herramienta pública de la NLM para enlazar nombres de medicamentos con
  RxNorm (la coincidencia aproximada de RxNav) bajo el mismo protocolo? ¿Permite aceptar productos
  sin revisión con una precisión de al menos 95 %?

## 1. Qué se había visto al escribir este plan

| Datos | Visto |
|---|---|
| dev | Todo, incluidas las 16 corridas de RxNav de la sección 6. |
| test2 | Los resultados de la v0.2.0 y la v0.2.1 para la regresión logística y gradient boosting. De RxNav, nada evaluado: sus respuestas se descargaron junto con las de dev para usar la misma versión de RxNorm, y solo se contaron sus líneas y estados para comprobar que la descarga estaba completa (4.000 respuestas, 0 errores). |
| test (v0.1.0) | No se usa en esta versión. |

## 2. El comparador

- **API:** Prescribable RxNorm API, `getApproximateMatch`
  (`https://rxnav.nlm.nih.gov/REST/Prescribe/approximateTerm.json`), con `maxEntries=100` (el
  máximo) y `option=1` (átomos de conceptos activos). Usa el mismo subconjunto de RxNorm del que
  sale el catálogo. Versión de RxNorm informada por la API: 02-Nov-2026, la misma del catálogo
  (API 3.1.358).
- **Descarga:** `scripts/rxnav_fetch.py`, corrido el 26-11-2026 entre las 13:35 y las 14:15 UTC
  desde el computador del autor, porque la API no es accesible desde el entorno de desarrollo. Unas
  10 consultas por segundo; la NLM pide no pasar de 20. 12.000 consultas, 0 errores.
- **Consulta:** la forma corta (`scripts/rxnav_queries.py`): ingredientes con su dosis, forma
  farmacéutica y vía, sin marca, envase ni laboratorio; se quitan los denominadores "/1" y los
  corchetes, y se agrega el cero inicial a los decimales. Se eligió en dev (sección 6).
- **Reglas del benchmark sobre la respuesta:**
  - solo átomos de fuente RXNORM. Los átomos MTHSPL son nombres de etiquetas de productos: en dev,
    con el texto completo, el primer átomo devuelto era el nombre de etiqueta del concepto correcto
    en 1.471 de 2.000 productos. Usarlos mediría la memoria de etiquetas, y un catálogo de otro
    país no tiene esos nombres;
  - solo conceptos SCD del catálogo: los conceptos retirados y los productos de marca no se
    ofrecen;
  - el orden de RxNav, sin reordenar.
- **Puntaje:** el de RxNav ordena los resultados de una consulta, pero no tiene un significado
  absoluto entre consultas. Se usa una calibración logística (`score=cal`) ajustada en 2.000
  productos de entrenamiento con su concepto en el catálogo (semilla 2027), el 10 % de ellos
  mostrado sin su concepto, como en el modelo del benchmark. Atributos: el percentil del puntaje de
  RxNav entre los de esos 2.000 productos, su distancia al segundo candidato y el logaritmo del
  número de candidatos.
- **Reglas de umbral:** `point`, `wilson`, `ltt` y `sgr`, con meta de 95 % y fijadas en dev. En
  dev solo la regla puntual encontró un umbral (sección 6).
- **Etiquetas:** `rxnav-inputshort-scorecal`, con `@wilson`, `@ltt` y `@sgr`.

## 3. Hipótesis (test2)

| | Hipótesis | Criterio |
|---|---|---|
| H8 | RxNav ordena peor los candidatos que el método del benchmark. | Acierto del primer candidato (productos cuyo concepto está en el catálogo) de RxNav menor que el de la regresión logística (84,1 % en test2), con un intervalo bootstrap pareado de la diferencia que excluye el cero y McNemar p < 0,05. |
| H9 | Con control del riesgo, RxNav no permite aceptar productos sin revisión. | Con `wilson`, `ltt` y `sgr`, la cobertura automática de RxNav es menor que la de la regresión logística con `wilson` (64,6 %), con un intervalo pareado que excluye el cero. En dev ninguna de esas tres reglas encontró umbral, así que en test2 RxNav no acepta nada por construcción: esta hipótesis queda decidida por dev y se reporta igual. |
| H10 | Descriptiva. | Con la regla puntual: precisión de RxNav en test2, su intervalo de Wilson y su cobertura. Además, respuesta entre los cinco primeros, productos fuera del catálogo aceptados y precisión de los productos con mayor puntaje al 5, 10, 20, 40 y 60 % de cobertura (`scripts/precision_at_coverage.py`), para RxNav, la regresión logística y gradient boosting. |

Lo esperable con lo visto en dev, escrito antes de evaluar:

- **H8:** en dev, 72,3 % contra 85,7 % (diferencia −13,3 puntos, IC −15,5 a −11,2).
- **H9:** cobertura 0 con las tres reglas.
- **H10:** con la regla puntual, en dev RxNav aceptó el 4,3 % de los productos con 95,3 % de
  precisión, justo sobre la meta; en test2 es probable que quede bajo ella, como le pasó a la
  regresión logística con esa regla. La precisión de sus productos con mayor puntaje estuvo entre
  89 % y 94 % en todas las coberturas medidas.

## 4. Comandos exactos

```
G=rules-dropexpected_form_missing-featuresv2-scorergb-stage5
R=rxnav-inputshort-scorecal
dmb freeze --version v0.2.2 --matcher rules-stage5@wilson --matcher $G@wilson \
  --matcher $R --matcher $R@wilson --matcher $R@ltt --matcher $R@sgr
# commit y etiqueta v0.2.2-pretest; después, una sola vez cada uno:
dmb eval --matcher rxnav --param input=short --param score=cal --split test2 --final
dmb eval --matcher rxnav --param input=short --param score=cal --threshold-rule wilson --split test2 --final
dmb eval --matcher rxnav --param input=short --param score=cal --threshold-rule ltt --split test2 --final
dmb eval --matcher rxnav --param input=short --param score=cal --threshold-rule sgr --split test2 --final
dmb compare --split test2 --version v0.2.2 --against-first --name rxnav \
  --matcher rules-stage5@wilson --matcher $R --matcher $R@wilson --matcher $R@ltt --matcher $R@sgr
python scripts/precision_at_coverage.py test2 rules-stage5@wilson $G@wilson $R@wilson \
  --out results/v0.2.2/test2_precision_at_coverage.json
```

- La regresión logística y gradient boosting no se vuelven a evaluar: se usan sus corridas de la
  v0.2.0 en test2, que aplicaron los umbrales de las mismas corridas de dev que congela este
  freeze.
- Después del freeze no se corre nada más en dev con estas etiquetas.

## 5. Límites conocidos

- **RxNav no está hecho para este uso.** Es una coincidencia léxica, sin conversión de unidades
  (por ejemplo, "400 mg/5 mL" frente a "80 MG/ML"), y la propia NLM recomienda tratar sus
  resultados como candidatos para revisión manual.
- **Tope de 100 átomos.** Los nombres de etiquetas ocupan la mayor parte de la respuesta (en dev,
  con la consulta corta, 114.497 de 166.831 átomos), y en 340 de los 2.000 productos de dev ningún
  candidato pasó el filtro. Eso desfavorece a RxNav, pero la API no permite pedir solo nombres de
  RxNorm.
- **La calibración usa 2.000 productos de entrenamiento**, no los 30.375, por el costo de consultar
  la API.
- **La API cambia cada mes.** Para reproducir, se usan las respuestas guardadas (sus SHA-256 están
  en la sección 7), que se archivarán con la versión enviada a la revista.

## 6. Decisiones tomadas con dev (exploratorias)

Datos vistos al tomarlas: dev. De test2, nada evaluado.

| Consulta, puntaje | Acierto top 1 | Entre los cinco primeros | Regla puntual: cobertura (precisión) | Wilson, LTT y SGR | ECE / Brier |
|---|---:|---:|---:|---|---:|
| Completa, percentil | 51,7 % | 58,6 % | 0,5 % (100 %) | sin umbral | 0,300 / 0,301 |
| Completa, calibrado | 51,7 % | 58,6 % | 5,3 % (95,3 %) | sin umbral | 0,063 / 0,165 |
| Corta, percentil | 72,3 % | 79,6 % | 1,4 % (96,4 %) | sin umbral | 0,304 / 0,279 |
| **Corta, calibrado (elegida)** | **72,3 %** | **79,6 %** | **4,3 % (95,3 %)** | **sin umbral** | **0,053 / 0,139** |

- Como las cuatro configuraciones tienen cobertura 0 con Wilson, se eligió por acierto top 1 (la
  consulta corta) y, después, por la cobertura con la regla puntual y la calibración (el puntaje
  calibrado).
- El detalle de las 16 corridas está en `results/v0.2.2/dev_rxnav.json`. La calibración elegida
  tiene coeficientes 1,372 (percentil), 3,423 (distancia al segundo), −0,46 (log del número de
  candidatos) e intercepto 1,07; de los 2.000 productos de entrenamiento, 1.608 tuvieron algún
  candidato después del filtro.
- Precisión de los productos con mayor puntaje en dev, al 5, 10, 20, 40 y 60 % de cobertura:
  RxNav 93,0; 91,5; 93,2; 93,5; 89,0 %. Regresión logística: 99,0; 99,5; 98,5; 98,9; 97,3 %.

## 7. Trazabilidad

- **Código.** Nuevos: `src/dmb/rxnav.py`, `src/dmb/matchers/rxnav.py`,
  `scripts/rxnav_queries.py`, `scripts/rxnav_fetch.py`, `scripts/precision_at_coverage.py` y
  `tests/test_rxnav.py` (92 pruebas en total). Frente a la etiqueta `v0.2.1`, el código existente
  solo cambia en dos líneas: la evaluación le pasa al matcher el nombre del split
  (`matcher.split = split`) y el matcher base declara ese atributo. `git diff v0.2.1` sobre las
  reglas, las formas, las dosis, la lectura, las métricas y la comparación da salida vacía.
- **Respuestas de RxNav** (`data/rxnav/`, fuera de git), SHA-256:
  - `responses_train_sample.jsonl`: `98e03f0f5efe9c8e80d8fc75f99fc9a76256e17c69fdf37cb7d14179da9c3829`
  - `responses_dev.jsonl`: `fc76cf66e311694e337a38ee30f3725a95cdd3eee5c4125e02f0b8d575a619f8`
  - `responses_test2.jsonl`: `d36e08432c664616145ea6ee8bb1f6cb8979f8cf0308dc944b2d455236945f0b`
- **Consultas**, SHA-256:
  - `queries_train_sample.jsonl`: `40c0346f3daf40b4faeec07ef4ef0972f3302e9ad38c764e64f33a77da6b2e89`
  - `queries_dev.jsonl`: `cf2dab16dd4a262e71bc7a8340268f098ff6cf62170f0da70c6d062b2102b3b6`
  - `queries_test2.jsonl`: `b51317f1db1cfec010492f9e768c32986b84a3d2cce56f7dcbf3bd078aea5495`
- **Datos y splits:** hashes en `results/v0.2.2/freeze.json`, verificados por `dmb compare`.
- **Registro:** este plan, el código y el freeze van en un commit con la etiqueta `v0.2.2-pretest`.
  Antes de evaluar test2 se comprueba que el SHA-256 de `responses_test2.jsonl` sigue siendo el de
  arriba.

## Enmiendas y desviaciones

Misma regla que en la v0.2.0. Ninguna por ahora.
