# Resultados de la v0.2.0 en test2

Evaluación final según el pre-registro (`plan.md`, Enmienda 1 y Desviación 1).

- Código: commit `d59debb`, etiqueta `v0.2.0-pretest` (empujada antes de evaluar).
- Fecha: 2026-11-26 (UTC). Cada matcher se evaluó **una sola vez** en test2 (`reports/test_runs.log`).
- Verificaciones de `dmb compare`: los 17 archivos de datos y splits coinciden con el freeze; los cuatro
  matchers usaron los umbrales congelados en dev, y los coeficientes de la regresión logística son
  los congelados.
- Comandos: los de la Enmienda 1, con `<v020>` =
  `--matcher rules --param stage=5 --param scorer=gb --param features=v2 --param drop=expected_form_missing`.
- Archivos: `test2/*.json` (métricas por matcher), `test2_comparison.json` (pruebas pareadas) y
  `test2_analysis.json` (análisis exploratorio, `scripts/test2_analysis.py`).

## 1. Tabla general (test2: 2.000 productos, 175 no están en el catálogo)

| | stage 4 | stage 5 (umbral puntual) | stage 5 (Wilson) | **v0.2.0** (Wilson) |
|---|---:|---:|---:|---:|
| Acierto top 1 (en catálogo) | 84,1 % | 84,1 % | 84,1 % | **85,8 %** |
| Respuesta en el top 5 | 92,3 % | 92,3 % | 92,3 % | 93,0 % |
| **Cobertura automática** | 50,6 % | 68,9 % | 64,6 % | **72,6 %** |
| Aceptados | 1.012 | 1.377 | 1.292 | 1.451 |
| Precisión de lo aceptado | 95,5 % | 94,6 % | 96,2 % | 95,0 % |
| Intervalo de Wilson 95 % | 94,0–96,6 | 93,3–95,7 | 95,0–97,1 | 93,8–96,0 |
| Aceptaciones falsas (total) | 46 | 74 | 49 | 72 |
| … de productos que no están en el catálogo | 9 | 25 | 19 | 28 |
| FAR_NIL (sobre 175) | 5,1 % | 14,3 % | 10,9 % | 16,0 % |
| ECE | 0,092 | 0,018 | 0,018 | 0,028 |
| Brier | 0,114 | 0,092 | 0,092 | **0,079** |

## 2. Hipótesis

### H1, control explícito del riesgo: **se cumple, sin margen**

- Criterio: precisión observada de la v0.2.0 en test2 ≥ 95 %.
- Resultado: **95,04 %** (1.379 de 1.451 aceptados), Wilson 93,8–96,0 %. Hay 72 falsos positivos,
  28 de ellos productos que no están en el catálogo.
- Con **una aceptación falsa más** (73) la precisión habría quedado en 94,97 % y H1 no se habría
  cumplido. El límite inferior de Wilson (93,8 %) está bajo 95 %: los datos no permiten afirmar con
  confianza que la precisión real de la v0.2.0 sea ≥ 95 %.
- Contexto (líneas base, mismo test2):
  - `rules-stage5` con umbral puntual: 94,6 % (93,3–95,7). **No cumple**, igual que en el test de
    la v0.1.0 (94,9 %).
  - `rules-stage5@wilson`: 96,2 % (95,0–97,1). Cumple, incluso con el límite inferior.

### H2, más cobertura con el mismo criterio de riesgo: **se cumple**

- Criterio: cobertura de la v0.2.0 > `rules-stage5@wilson`, con el intervalo bootstrap pareado
  (95 %) excluyendo 0.
- Resultado: **+7,95 puntos** (6,5 a 9,5), de 64,6 % a 72,6 %, sobre los mismos 2.000 productos.
- Transiciones entre bandas:
  - 199 productos pasan de revisión a aceptación: 164 bien, 35 mal (13 de ellos no están en el
    catálogo, 22 con otro concepto del catálogo).
  - 40 pasan de aceptación a revisión (26 de ellos eran aciertos de la línea base).
  - 35 pasan de revisión a abstención; 1 de abstención a revisión.
- Balance neto: +136 aceptaciones correctas y +23 aceptaciones falsas. **Precisión incremental:
  85,5 %.** La cobertura extra es real, pero lo que se agrega es bastante más riesgoso que lo que ya
  se aceptaba: la precisión total baja de 96,2 % a 95,0 %.

### H3, menos productos inexistentes aceptados: **no se cumple (resultado negativo)**

- Criterio: menos aceptaciones de productos que no están en el catálogo que `rules-stage5@wilson`.
- Resultado: **28 de 175 (16,0 %) contra 19 de 175 (10,9 %)**. Diferencia pareada +5,1 puntos
  (0,6 a 9,1); McNemar sobre los 175: p = 0,049. La v0.2.0 acepta **más**, no menos.
- Es la misma dirección que se vio en dev (27 contra 23 de 185). La regla de selección premiaba la
  cobertura y usaba los inexistentes solo como desempate.
- Exploratorio (no cambia el veredicto):
  - 22 de los 28 difieren del concepto retirado solo en la forma (19) o en la forma y el volumen
    (3): son **formas hermanas**. Los atributos v2 no resolvieron este problema.
  - Los 28 vienen de solo 13 conceptos retirados: 8 son "salicylic acid 20 MG/ML Medicated Liquid
    Soap" y 5 son "lidocaine 50 MG/ML Rectal Cream". La línea base reparte sus 19 en 14 conceptos.
    Los errores están agrupados por concepto, y la prueba por producto los trata como
    independientes. Para una versión futura conviene pre-registrar un bootstrap por concepto.
  - En varios de esos casos, la descripción del NDC dice "CREAM TOPICAL" o "LIQUID TOPICAL", y la
    forma aceptada (Topical Cream, Topical Solution) es la que el texto sugiere. La etiqueta oficial
    es otra forma hermana. Es una limitación de la tarea que vale la pena discutir, no un rescate
    de H3.
  - Lado positivo, descriptivo: la v0.2.0 manda **72** de los 175 directo a "no está en el catálogo"
    (la línea base, 41), porque su umbral de abstención es más alto.

### H4, debilidades por categoría: **descriptiva**

| Subgrupo (n en test2) | | Línea base (Wilson) | v0.2.0 |
|---|---|---:|---:|
| Dentales (51, 1 inexistente) | Acierto top 1 | 36,0 % | 36,0 % |
| | Aceptaciones falsas / aceptados | 6 / 16 (37,5 %) | 2 / 15 (13,3 %) |
| Inhalados (39, 5 inexistentes) | Acierto top 1 | 23,5 % | 23,5 % |
| | Aceptaciones falsas / aceptados | 3 / 9 (33,3 %) | 2 / 9 (22,2 %) |
| Kits (28, 2 inexistentes) | Acierto top 1 | 0 % | 0 % |
| | Aceptados | 0 | 0 |

- En dentales e inhalados, la v0.2.0 acepta casi lo mismo con menos errores. Sin embargo, el acierto
  top 1 no cambia: el problema está en la generación de candidatos, no en el puntaje.
- Con n tan chicos (16 y 9 aceptados) esto es solo descriptivo, como estaba previsto.
- Los kits siguen sin resolverse: ninguno de los dos los acepta nunca.

## 3. Otras comparaciones pareadas (incluidas en `dmb compare`, sin hipótesis propia)

- **Umbral Wilson contra puntual** (`rules-stage5`):
  - Cobertura: −4,25 puntos (−5,1 a −3,4).
  - Inexistentes aceptados: de 25 a 19 (−3,4 puntos, −6,3 a −1,1; McNemar p = 0,031).
  - Precisión: de 94,6 % a 96,2 %, y pasa de no cumplir la meta a cumplirla.
- **v0.2.0 contra la línea base**:
  - Acierto top 1: +1,7 puntos (0,9 a 2,5), McNemar p < 0,001.
  - Brier: mejora (0,092 → 0,079).
  - ECE: empeora (0,018 → 0,028).
- **stage 5 contra stage 4** (umbral puntual): +18,25 puntos de cobertura (16,0 a 20,5), pero 25
  inexistentes aceptados contra 9 (McNemar p = 0,002).

## 4. Estabilidad dev → test2

| | Cobertura dev → test2 | Precisión dev → test2 | Inexistentes aceptados dev → test2 |
|---|---|---|---|
| `rules-stage5@wilson` | 64,7 % → 64,6 % | 96,2 % → 96,2 % | 23/185 → 19/175 |
| v0.2.0 | 72,7 % → 72,6 % | 96,2 % → 95,0 % | 27/185 → 28/175 |

- La cobertura de ambas se mantiene.
- La precisión de la línea base se mantiene; la de la v0.2.0 baja 1,1 puntos.
- Explicación plausible, no probada: la v0.2.0 se eligió entre 82 configuraciones en dev, y el
  ganador de una selección así suele verse mejor en dev de lo que es (sesgo del ganador). La línea
  base no compitió contra alternativas.

## 5. Lectura para el paper

- **Lo más sólido es el control del riesgo.** Elegir el umbral con el límite inferior de Wilson
  cumple la meta en datos nuevos. El umbral puntual no la cumple, y eso se repite en dos tests
  independientes (94,9 % y 94,6 %).
- **Gradient boosting con atributos v2 compra cobertura (+8 puntos) y la paga.** Gasta casi todo el
  margen de precisión (95,04 %) y acepta más productos inexistentes (H3 negativa). Es un
  compromiso, no una mejora estricta.
- **Lo que queda abierto apunta a la Etapa 3:** las formas hermanas cuando el concepto correcto no
  está en el catálogo, y la generación de candidatos (dentales, inhalados, kits).
- Las hipótesis se reportan tal como quedaron. Cualquier cambio de ahora en adelante es exploratorio
  y necesitaría otro split independiente para confirmarse (por ejemplo, un test temporal con una
  descarga futura del NDC).
