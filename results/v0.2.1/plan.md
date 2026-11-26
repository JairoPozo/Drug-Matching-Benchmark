# Pre-registro de la v0.2.1: umbrales con garantía formal

Escrito y commiteado **antes** de evaluar en test2 las reglas nuevas (`ltt` y `sgr`). Lo que está
aquí no se cambia después de ver resultados; los cambios van en "Enmiendas y desviaciones", con la
misma regla de la v0.2.0 (`results/v0.2.0/plan.md`).

- Punto de partida: commit `33d3ce7` (la v0.2.0 y su evaluación secundaria). No se re-entrena
  nada: los modelos son los de la v0.2.0 y solo cambia cómo se elige el umbral de aceptación.
- Pregunta: la regla `wilson` de la v0.2.0 revisa cada umbral por separado, sin corregir por
  haber revisado muchos, así que no es una garantía formal. ¿Se comporta como una regla que sí la
  tiene? ¿Cuánta cobertura cuesta la garantía?

## 1. Qué se había visto al escribir este plan

| Datos | Visto |
|---|---|
| dev | Todo, incluidas las corridas de `ltt` y `sgr` y el ensayo del remuestreo (sección 7). |
| test2 | Los resultados de la v0.2.0 con las reglas `point` y `wilson` en los dos modelos, incluida la lista de aceptaciones falsas que fue a la revisión farmacéutica. De `ltt` y `sgr`, nada. |
| test (v0.1.0) | La evaluación secundaria de la v0.2.0 con `wilson`. No se usa en esta versión. |

Consecuencia: los umbrales de `ltt` quedan a menos de 0,006 de los de `wilson`, y los de `sgr`
por encima. En test2, `ltt` acepta casi los mismos productos que `wilson` (más unos pocos) y `sgr`
un subconjunto de ellos, y esos productos ya se vieron. Por eso la evaluación en test2 (H5 y H6)
aporta poca información nueva. El análisis principal de esta versión es el remuestreo (H7), que
mide con qué frecuencia cada regla falla la meta.

## 2. Reglas comparadas

Meta: precisión de las aceptaciones ≥ 95 %. El umbral se elige en dev y se aplica tal cual en
test2. Precisión = respuestas top 1 correctas entre las aceptadas; aceptar un producto que no está
en el catálogo cuenta como error.

| Regla | Qué hace | Garantía |
|---|---|---|
| `point` (v0.1.0) | El umbral de mayor cobertura cuya precisión observada en dev es ≥ 95 %. | Ninguna. |
| `wilson` (v0.2.0) | El umbral de mayor cobertura cuyo límite inferior de Wilson (95 %, bilateral) es ≥ 95 %. | Ninguna formal: revisa cada umbral por separado y se queda con el más bajo que pasa. |
| `ltt` | Learn then Test [Angelopoulos et al.] con *fixed-sequence testing*. Recorre los umbrales 0,950; 0,949; …; 0,000 (951 valores, paso 0,001). En cada uno prueba H0: tasa de error de las aceptaciones > 5 %, con la prueba binomial exacta a nivel δ = 0,05. Se detiene en el primero que no rechaza y se queda con el anterior. | Con probabilidad ≥ 1 − δ sobre la muestra de calibración, la precisión en la población es ≥ 95 %, si la calibración y los datos nuevos son intercambiables. |
| `sgr` | Selection with Guaranteed Risk [Geifman y El-Yaniv, Algoritmo 1]. Búsqueda binaria sobre los puntajes de la muestra, con la cota superior de Clopper-Pearson de la tasa de error a nivel δ / ⌈log2 m⌉, δ = 0,05. Se queda con el umbral más bajo probado cuya cota es < 5 %. | La misma, por el teorema del paper. |

Modelos, en adelante `<lr>` y `<gb>`:

- `<lr>` = `rules-stage5`: regresión logística, la línea base de la v0.2.0.
- `<gb>` = `rules-dropexpected_form_missing-featuresv2-scorergb-stage5`: gradient boosting, la
  v0.2.0.

## 3. Hipótesis

| | Hipótesis | Criterio |
|---|---|---|
| H5 | Las reglas con garantía cumplen la meta en datos nuevos. | En test2, la precisión observada de `ltt` y de `sgr` es ≥ 95 % en los dos modelos (4 casos). Se reportan su intervalo de Wilson, las aceptaciones, las aceptaciones falsas y cuántas son de productos que no están en el catálogo. |
| H6 | Cuánto cuesta la garantía en test2. Descriptiva. | Para cada modelo: diferencia de cobertura `ltt` − `wilson` y `sgr` − `wilson`, en puntos, con bootstrap pareado del 95 %; diferencia en aceptaciones de productos que no están en el catálogo (McNemar exacta sobre los 175); matriz de transiciones entre bandas. |
| H7a | La implementación respeta la garantía. Es un chequeo del código, no de la teoría. | En el remuestreo (sección 4), la tasa de violación de `ltt` y de `sgr` es ≤ 5 % en los dos modelos. Una tasa > 6,4 % (5 % más dos errores de Monte Carlo) se lee como un error de implementación: se busca, se corrige en una versión nueva y se reporta, sin reescribir este resultado. |
| H7b | Con qué frecuencia falla cada regla y cuánto cubre. Descriptiva. | Tasa de violación de `point` y `wilson`. Cobertura media y percentiles 2,5–97,5 de todas las reglas, contra `wilson` y contra el mejor umbral de la población. |

Lo esperable con lo ya visto, escrito antes de evaluar:

- **H5.** `<lr>` con `wilson` tuvo 96,21 % en test2, así que `<lr>` con `ltt` y con `sgr`
  probablemente cumplen. `<gb>` con `wilson` tuvo 95,04 %: 1.379 correctas de 1.451, cuando el
  mínimo para 95 % es 1.378,45. `<gb>` con `ltt` acepta además los productos con puntaje entre
  0,784 y 0,7895; si agrega 8 o menos, basta que uno sea incorrecto para quedar bajo 95 %. Eso
  no contradiría la garantía, que habla de la precisión en la población con probabilidad 1 − δ y
  no de cada muestra finita. Por eso el análisis que decide es H7.
- **H6.** En dev, `ltt` cubrió 0,3 (`<lr>`) y 0,15 (`<gb>`) puntos más que `wilson`, y `sgr`
  1,7 y 2,15 puntos menos.
- **H7.** En el ensayo con dev como población (sección 7), violación: `point` 43–47 %, `wilson`
  1,7–2,0 %, `ltt` 2,8–3,6 %, `sgr` 0,2–0,7 %.

## 4. Diseño del remuestreo (H7)

- **Población:** los 4.000 productos de dev y test2, con los puntajes que cada modelo ya les dio
  en sus corridas completas (`<lr>@wilson` y `<gb>@wilson`; el puntaje no depende de la regla).
  No se re-entrena nada.
- **Repeticiones:** 1.000, semilla 2026, las mismas muestras para los dos modelos. En cada una se
  sacan 2.000 productos con reemplazo (el tamaño de dev) y se elige el umbral con cada regla.
  Luego se mide, en la población completa y en ese umbral: cobertura, precisión y tasa de
  aceptación de productos que no están en el catálogo.
- **Violación:** precisión de la población < 95 % en el umbral elegido. Si una regla no encuentra
  umbral (no acepta nada), no es violación: se reporta aparte y cuenta como cobertura 0.
- **Por qué este diseño:** las muestras son i.i.d. de una población fija, así que la garantía se
  aplica tal como está enunciada. Para `ltt` es exacta. Para `sgr` es la del teorema de Geifman y
  El-Yaniv; como sus umbrales salen de la propia muestra, H7a también la revisa en la práctica. La
  grilla de `ltt` se eligió mirando dev (sección 7), pero eso la hace depender de la población y
  no de las muestras, así que no afecta este cálculo.
- **Referencia:** el mejor umbral de la población, el de mayor cobertura con precisión de la
  población ≥ 95 %. Solo se conoce sabiendo las respuestas de todos los productos.
- **Extra descriptivo:** `ltt` con δ = 0,025, porque en dev `wilson` aceptó exactamente los mismos
  productos que ella en los dos modelos. Se reporta en qué fracción de las repeticiones las dos
  aceptan el mismo conjunto en la muestra y en cuál `wilson` acepta más. Una diferencia puede venir
  de tres cosas: Wilson es una aproximación y la prueba binomial es exacta; la grilla de `ltt` tiene
  paso 0,001; y `wilson` puede saltarse un umbral que falla y quedarse con uno más bajo, que es el
  problema de multiplicidad.
- **Script:** `scripts/threshold_resampling.py`. Resultado en
  `results/v0.2.1/resampling_dev_test2.json`.

## 5. Evaluación en test2: comandos exactos

```
dmb freeze --version v0.2.1 \
  --matcher rules-stage5@wilson --matcher rules-stage5@ltt --matcher rules-stage5@sgr \
  --matcher <gb>@wilson --matcher <gb>@ltt --matcher <gb>@sgr
# commit y etiqueta v0.2.1-pretest; después, una sola vez cada uno:
dmb eval --matcher rules --param stage=5 --threshold-rule ltt --split test2 --final
dmb eval --matcher rules --param stage=5 --threshold-rule sgr --split test2 --final
dmb eval --matcher rules --param stage=5 --param scorer=gb --param features=v2 \
  --param drop=expected_form_missing --threshold-rule ltt --split test2 --final
dmb eval --matcher rules --param stage=5 --param scorer=gb --param features=v2 \
  --param drop=expected_form_missing --threshold-rule sgr --split test2 --final
dmb compare --split test2 --version v0.2.1 --against-first --name lr \
  --matcher rules-stage5@wilson --matcher rules-stage5@ltt --matcher rules-stage5@sgr
dmb compare --split test2 --version v0.2.1 --against-first --name gb \
  --matcher <gb>@wilson --matcher <gb>@ltt --matcher <gb>@sgr
python scripts/threshold_resampling.py dev test2
```

- `wilson` no se vuelve a evaluar en test2. La comparación usa sus corridas de la v0.2.0, que
  aplicaron los umbrales de las mismas corridas de dev que congela este freeze; `dmb compare` lo
  verifica.
- Después del freeze no se corre nada más en dev con estas seis etiquetas: test2 usa los umbrales
  de la última corrida completa en dev, y `dmb compare` marcaría la diferencia.
- Se reportan todas las hipótesis, se cumplan o no.

## 6. Límites conocidos

- **Intercambiabilidad.** La garantía supone que dev y los datos nuevos vienen de la misma
  distribución. Un cambio en el tiempo (descargas futuras del NDC, productos nuevos) no está
  cubierto.
- **Es sobre la muestra de calibración.** Una de cada 20 muestras de dev puede dar un umbral
  demasiado permisivo. No dice nada de cada lote de productos nuevos.
- **Optimismo de dev.** El modelo de la v0.2.0 se eligió en dev, así que sus puntajes en dev
  pueden ser algo optimistas; afecta por igual a todas las reglas.
- **Alcance del remuestreo.** Mide las reglas sobre la población de estos 4.000 productos; no mide
  cómo generalizan los modelos a otra distribución.
- **Qué mide la precisión.** Es la de la respuesta top 1 entre las aceptadas; no cubre la banda de
  revisión.

## 7. Decisiones tomadas con dev antes de este plan (exploratorias)

Datos vistos al tomarlas: dev. De test2, nada de `ltt` ni de `sgr`.

1. **δ y meta.** δ = 0,05 y la meta de 95 % se fijaron al implementar las reglas, antes de
   cualquier corrida. `ltt` con δ = 0,025 se calculó después, al ver que en dev coincidía con
   `wilson`, y queda solo como descriptiva.
2. **Inicio de la grilla de `ltt`.**
   - La grilla empezaba en 0,99. Un primer remuestreo en dev, con mitades de 1.000 productos,
     mostró que en el 6,4 % de las repeticiones de `<lr>` la secuencia se detenía en el primer
     umbral, sin aceptar nada.
   - La causa: sobre 0,99 hay pocos productos (332 en dev, unos 166 por mitad, con 4 errores). Si
     los 4 caen en la mitad de calibración (6,2 % de las veces), la prueba en 0,99 no rechaza
     (p = 0,078) y la secuencia termina.
   - Se cambió el inicio a 0,950, la meta misma. En dev completo, las dos grillas dan exactamente
     los mismos umbrales (`<lr>` 0,823; `<gb>` 0,784), así que el cambio no alteró el resultado de
     dev.
   - El orden de la secuencia debería fijarse antes de ver los datos de calibración. Para la
     corrida en dev esto es una desviación del protocolo estricto de `ltt`; su efecto es sobre la
     potencia (no detenerse antes de empezar), y no cambió ningún umbral.
3. **Diseño del remuestreo.** Ese primer remuestreo medía la precisión en la otra mitad. Se
   reemplazó por el diseño de la sección 4 porque la precisión de una mitad finita mezcla el error
   de la regla con el ruido de muestreo de la propia mitad: una regla exacta parecería fallar más
   que δ.
4. **Ensayo del diseño final**, con solo dev como población (`python
   scripts/threshold_resampling.py dev`, guardado en `results/v0.2.1/resampling_dev.json`):

   | Regla | Violación `<lr>` | Cobertura media `<lr>` | Violación `<gb>` | Cobertura media `<gb>` |
   |---|---:|---:|---:|---:|
   | `point` | 42,9 % | 67,9 % | 46,5 % | 76,2 % |
   | `wilson` | 1,7 % | 64,5 % | 2,0 % | 72,4 % |
   | `ltt` | 2,8 % | 65,0 % | 3,6 % | 72,9 % |
   | `sgr` | 0,7 % | 62,9 % | 0,2 % | 70,9 % |
   | `ltt` con δ = 0,025 | 1,6 % | 64,4 % | 1,8 % | 72,2 % |
   | Mejor umbral de la población | — | 68,2 % | — | 75,9 % |

## 8. Trazabilidad

- **Código de los modelos sin cambios desde la etiqueta `v0.2.0`.**
  `git diff v0.2.0 -- src/dmb/matchers src/dmb/forms.py src/dmb/strength.py src/dmb/parse.py
  src/dmb/rxvocab.py src/dmb/evaluate.py src/dmb/config.py` da salida vacía. Cambian
  `metrics.py` (reglas `ltt` y `sgr`), `cli.py` y `compare.py` (opciones `--against-first` y
  `--name` de `dmb compare`).
- **Reglas anteriores intactas.** Con el código actual, `point` y `wilson` dan exactamente los
  umbrales congelados en la v0.2.0: `<lr>` 0,7513 y 0,8285; `<gb>` 0,7895.
- **Datos y splits.** Sus hashes quedan en `results/v0.2.1/freeze.json`, y `dmb compare` los
  verifica.
- **Registro.** Este plan, el código y el freeze van en un commit con la etiqueta
  `v0.2.1-pretest`.

## Enmiendas y desviaciones

Misma regla que en la v0.2.0. Ninguna por ahora.
