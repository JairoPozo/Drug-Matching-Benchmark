# Resultados de la v0.2.2: comparación con RxNav

Evaluación según el pre-registro (`plan.md`). Se reportan todas las hipótesis.

- Código: commit `e8e054f`, etiqueta `v0.2.2-pretest`.
- Fecha: 2026-11-26 (UTC). Las cuatro etiquetas de RxNav se evaluaron **una sola vez** en test2.
  Antes de evaluar se comprobó que el SHA-256 de `data/rxnav/responses_test2.jsonl` seguía siendo
  el del plan (`d36e0843…`).
- Verificaciones de `dmb compare`: datos y splits iguales al freeze, umbrales de las corridas de dev
  congeladas y coeficientes congelados, en las cinco etiquetas comparadas.
- Archivos: `test2/*.json` (métricas de RxNav), `test2_comparison_rxnav.json` (pruebas pareadas
  contra la regresión logística con Wilson) y `test2_precision_at_coverage.json`.

## 1. test2 (2.000 productos, 175 no están en el catálogo)

| | Regresión logística, Wilson | RxNav, regla puntual | RxNav, Wilson / LTT / SGR |
|---|---:|---:|---:|
| Acierto del primer candidato (en catálogo) | 84,1 % | 71,0 % | 71,0 % |
| Respuesta entre los cinco primeros | 92,3 % | 78,0 % | 78,0 % |
| Umbral (fijado en dev) | 0,8285 | 0,9823 | ninguno |
| Cobertura automática | 64,6 % | 4,8 % | 0 % |
| Aceptados | 1.292 | 96 | 0 |
| Precisión de lo aceptado (IC de Wilson 95 %) | 96,2 % (95,0–97,1) | 94,8 % (88,4–97,8) | — |
| Aceptaciones falsas (fuera del catálogo) | 49 (19) | 5 (0) | 0 |
| ECE / Brier | 0,018 / 0,092 | 0,032 / 0,144 | 0,032 / 0,144 |

## 2. Hipótesis

### H8, RxNav ordena peor los candidatos: **se cumple**

Acierto del primer candidato: 71,0 % contra 84,1 %, una diferencia de −13,1 puntos (IC bootstrap
pareado −15,1 a −11,1; McNemar p < 0,001). En dev había sido −13,3.

### H9, con control del riesgo RxNav no acepta productos sin revisión: **se cumple, por construcción**

Con Wilson, LTT y SGR no hubo umbral en dev, así que RxNav no aceptó ningún producto de test2:
cobertura 0 contra 64,6 % (diferencia −64,6 puntos, IC −66,75 a −62,5). Como dice el plan, esta
hipótesis quedó decidida en dev.

### H10, descriptiva

- **Regla puntual.** RxNav aceptó 96 productos (4,8 %) con 94,8 % de precisión: 5 errores, ninguno
  de un producto fuera del catálogo. Queda bajo la meta, como la regresión logística con esa misma
  regla (94,6 % en test2), aunque con tan pocos aceptados el intervalo es ancho (88,4–97,8).
- **Respuesta entre los cinco primeros:** 78,0 % contra 92,3 %.
- **Precisión de los productos con mayor puntaje**, según la cobertura:

  | Cobertura | 5 % | 10 % | 20 % | 40 % | 60 % |
  |---|---:|---:|---:|---:|---:|
  | Regresión logística | 100 % | 100 % | 98,8 % | 98,3 % | 97,0 % |
  | Gradient boosting (v0.2.0) | 97,0 % | 98,5 % | 99,3 % | 99,1 % | 97,7 % |
  | RxNav | 93,0 % | 93,0 % | 92,5 % | 90,7 % | 86,6 % |

  Ni siquiera los productos en que RxNav más confía llegan a 95 %: por eso ninguna regla con
  control del riesgo encuentra un umbral.

## 3. Lectura para el artículo

1. Bajo las mismas reglas (sin nombres de etiquetas, solo conceptos del catálogo), la coincidencia
   aproximada de RxNav acierta 13 puntos menos que el método del benchmark y no permite aceptar
   productos sin revisión con una precisión de 95 %.
2. No es una crítica a RxNav: es una herramienta de búsqueda léxica, sin conversión de unidades, y
   la propia NLM recomienda revisar sus resultados a mano. El resultado muestra qué agrega el
   conocimiento farmacéutico estructurado (dosis normalizadas, formas y conversiones) cuando la
   meta es aceptar sin revisión.
3. Como herramienta de apoyo a la revisión sí sirve: en el 78 % de los productos la respuesta está
   entre sus cinco primeros candidatos.
4. Límite que desfavorece a RxNav: la API devuelve como máximo 100 resultados y la mayoría son
   nombres de etiquetas, que el benchmark excluye. En 340 productos de dev no quedó ningún
   candidato.
