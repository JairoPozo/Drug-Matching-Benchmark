# Pre-registro de la v0.2.3: comparación con SapBERT

Escrito y commiteado **antes** de evaluar SapBERT en test2. Los cambios van en "Enmiendas y
desviaciones", con la misma regla de la v0.2.0.

- Punto de partida: commit `315ce4e` (etiqueta `v0.2.2`). No cambian los modelos del benchmark ni
  las reglas de umbral.
- Pregunta: ¿cómo rinde un enlazador neuronal del estado del arte, SapBERT, bajo el mismo
  protocolo? ¿Ordena mejor los candidatos? ¿Permite aceptar productos sin revisión con precisión de
  al menos 95 %?

## 1. Qué se había visto al escribir este plan

| Datos | Visto |
|---|---|
| dev | Todo, incluidas las 16 corridas de SapBERT de la sección 6. |
| test2 | Los resultados de la v0.2.0, la v0.2.1 y la v0.2.2. De SapBERT, nada evaluado: sus candidatos se calcularon junto con los de dev, y solo se contaron las líneas del archivo (4.000) para comprobar que estaba completo. |

## 2. El comparador

- **Modelo:** SapBERT (`cambridgeltl/SapBERT-from-PubMedBERT-fulltext`), vector [CLS] normalizado,
  máximo 128 tokens. Calculado con `scripts/sapbert_embed.py` en el computador del autor el
  26-11-2026 (torch 2.15.0 en CPU, transformers 5.24.1), porque el entorno de desarrollo no
  accede a Hugging Face. El hash exacto de la revisión del modelo no quedó registrado por el script;
  se agrega en `resultados.md` desde la caché del autor.
- **Índice:** todos los nombres de RxNorm (fuente RXNORM, sin suprimir, tipos SCD, PSN y SY) de los
  10.888 conceptos del catálogo: 26.981 nombres en minúsculas, sin duplicados
  (`scripts/sapbert_names.py`). Los conceptos retirados no se indexan. Son recursos que el benchmark
  permite: nombres de RxNorm, no de etiquetas.
- **Candidatos:** los 100 conceptos con mayor similitud coseno; la de un concepto es la de su mejor
  nombre.
- **Puntaje:** la misma calibración logística que RxNav (`score=cal`), ajustada en los mismos 2.000
  productos de entrenamiento.
- **Reglas de umbral:** `wilson` (la del benchmark) y `ltt` (la recomendada en la v0.2.1), con meta de
  95 %, fijadas en dev.
- **Dos configuraciones, las dos evaluadas en test2** (sección 6):
  - **A** `sapbert-inputfull-scorecal`: la que elige la regla de selección del benchmark (mayor
    cobertura en dev con Wilson).
  - **B** `sapbert-inputshort-scorecal`: la de mayor acierto top 1 en dev, que además es el uso
    habitual de SapBERT (menciones cortas).

## 3. Hipótesis (test2)

| | Hipótesis | Criterio |
|---|---|---|
| H11 | SapBERT ordena los candidatos mejor que el generador del benchmark. | Acierto del primer candidato de B mayor que el de la regresión logística (84,1 % en test2), con un IC bootstrap pareado de la diferencia que excluye el cero. |
| H12 | Con control del riesgo, SapBERT acepta menos productos sin revisión. | Con Wilson, la cobertura automática de A y de B es menor que la de la regresión logística con Wilson (64,6 %), con IC pareados que excluyen el cero. |
| H13 | Descriptiva. | Con Wilson y LTT, para A y B: precisión en test2 con su intervalo, cobertura, productos fuera del catálogo aceptados (McNemar contra la regresión logística) y precisión de los productos con mayor puntaje al 5, 10, 20, 40 y 60 % de cobertura. |

Lo esperable con lo visto en dev, escrito antes de evaluar:

- **H11:** en dev, B acertó 88,2 % contra 85,7 % (+2,5 puntos, IC 1,0 a 4,0; McNemar p = 0,001). A,
  84,1 % (−1,6, IC −3,4 a 0,3).
- **H12:** en dev, cobertura con Wilson de 43,0 % (B) y 46,15 % (A), contra 64,7 % (−21,7 y −18,6
  puntos).
- **H13:** en dev, B aceptó 7 productos fuera del catálogo con Wilson, contra 23 de la regresión
  logística (McNemar p < 0,001), y A, 18 (p = 0,42).

## 4. Comandos exactos

```
G=rules-dropexpected_form_missing-featuresv2-scorergb-stage5
A=sapbert-inputfull-scorecal
B=sapbert-inputshort-scorecal
dmb freeze --version v0.2.3 --matcher rules-stage5@wilson --matcher $G@wilson \
  --matcher $A@wilson --matcher $A@ltt --matcher $B@wilson --matcher $B@ltt
# commit y etiqueta v0.2.3-pretest; después, una sola vez cada uno:
dmb eval --matcher sapbert --param input=full --param score=cal --threshold-rule wilson --split test2 --final
dmb eval --matcher sapbert --param input=full --param score=cal --threshold-rule ltt --split test2 --final
dmb eval --matcher sapbert --param input=short --param score=cal --threshold-rule wilson --split test2 --final
dmb eval --matcher sapbert --param input=short --param score=cal --threshold-rule ltt --split test2 --final
dmb compare --split test2 --version v0.2.3 --against-first --name sapbert \
  --matcher rules-stage5@wilson --matcher $A@wilson --matcher $A@ltt --matcher $B@wilson --matcher $B@ltt
python scripts/precision_at_coverage.py test2 rules-stage5@wilson $G@wilson $A@wilson $B@wilson \
  --out results/v0.2.3/test2_precision_at_coverage.json
```

Antes de evaluar se comprueba que el SHA-256 de `data/sapbert/responses_test2.jsonl` sigue siendo el
de la sección 7. Después del freeze no se corre nada más en dev con estas etiquetas.

## 5. Límites conocidos

- **Sin ajuste fino.** SapBERT se usa tal como se publicó; ajustarlo con los productos de
  entrenamiento podría mejorarlo y queda para la Etapa 3.
- **Nombres en el índice.** El índice incluye sinónimos de RxNorm, como "25 mg in 5 ml oral
  suspension", que el generador de reglas no usa. Son recursos permitidos y forman parte de lo que se
  compara.
- **Calibración con 2.000 productos de entrenamiento**, igual que RxNav.
- **Dos configuraciones en test2.** Cada una tiene su hipótesis y las dos se reportan, sin elegir
  después la mejor.

## 6. Decisiones tomadas con dev (exploratorias)

Datos vistos: dev. De test2, nada evaluado.

| Consulta, puntaje | Acierto top 1 | Entre los cinco primeros | Cobertura con Wilson (precisión) | Con LTT | Fuera del catálogo aceptados (Wilson) | ECE / Brier |
|---|---:|---:|---:|---:|---:|---:|
| Completa, percentil | 84,1 % | 96,8 % | sin umbral | sin umbral | — | 0,298 / 0,264 |
| **Completa, calibrado (A)** | **84,1 %** | **96,8 %** | **46,15 % (96,4 %)** | **46,65 %** | **18** | **0,051 / 0,129** |
| Corta, percentil | 88,2 % | 96,7 % | 32,15 % (96,7 %) | sin umbral | 4 | 0,376 / 0,284 |
| **Corta, calibrado (B)** | **88,2 %** | **96,7 %** | **43,0 % (96,5 %)** | **43,6 %** | **7** | **0,076 / 0,112** |
| Regresión logística (referencia) | 85,7 % | 93,3 % | 64,7 % (96,2 %) | 65,0 % | 23 | 0,021 / 0,090 |

- Precisión de los productos con mayor puntaje en dev al 5, 10, 20, 40 y 60 % de cobertura: B 98,0;
  98,0; 98,0; 97,4; 94,8 %. A 98,0; 98,0; 98,0; 97,6; 93,4 %. Regresión logística 99,0; 99,5; 98,5;
  98,9; 97,3 %.
- Exploratorio: de los 1.815 productos de dev con concepto en el catálogo, ambos métodos aciertan
  1.483; solo las reglas, 72; solo SapBERT (B), 117; ninguno, 143. Cuando coinciden en el primer
  candidato (1.564 productos), aciertan en el 94,8 %. Sugiere que combinarlos podría mejorar los
  dos; queda para la Etapa 3 y no se evalúa en test2.
- El detalle de las 16 corridas está en `results/v0.2.3/dev_sapbert.json`.

## 7. Trazabilidad

- **Código.** Nuevos: `scripts/sapbert_names.py`, `scripts/sapbert_embed.py`, el matcher
  `sapbert` (subclase del de RxNav en `src/dmb/matchers/rxnav.py`) y una prueba (93 en total). El
  matcher de RxNav ahora lee la carpeta y las fuentes desde atributos de clase; se verificó que da
  exactamente los mismos candidatos y puntajes que su corrida congelada en dev (0 productos con
  diferencias), sin crear una corrida nueva.
- **Archivos de SapBERT** (`data/sapbert/`, fuera de git), SHA-256:
  - `catalog_names.jsonl`: `e5b5f611ea840d9837273b98328a5adfeb29dc1ca679ab22d3093e8d6f113efb`
  - `name_embeddings.npy`: `bc3d5c60ef3755191a1cbee24a8ca9984564270fd198ad126e230e5562d1951c`
  - `responses_train_sample.jsonl`: `e41173e235abee89c06fd99d11546f178a4320ad44efc0aec07a30b40f3ebbb2`
  - `responses_dev.jsonl`: `a3e0b8a9cd4a6ffa91b9f3a7bb96b9e8f5218ac951756e39ec8bde6a806d584b`
  - `responses_test2.jsonl`: `85883b11d15efd4940523bca0583b10c40edba5a303d5e46ccbd89a88e5e5dae`
- **Consultas:** las mismas de la v0.2.2 (`data/rxnav/queries_*.jsonl`, hashes en su plan).
- **Registro:** este plan, el código y el freeze van en un commit con la etiqueta `v0.2.3-pretest`.

## Enmiendas y desviaciones

Misma regla que en la v0.2.0. Ninguna por ahora.
