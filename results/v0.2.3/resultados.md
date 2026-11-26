# Resultados de la v0.2.3: comparación con SapBERT

Evaluación según el pre-registro (`plan.md`). Se reportan todas las hipótesis.

- Código: commit `00cc137`, etiqueta `v0.2.3-pretest`.
- Fecha: 2026-11-26 (UTC). Las cuatro etiquetas de SapBERT se evaluaron **una sola vez** en test2.
  Antes de evaluar se comprobó que el SHA-256 de `data/sapbert/responses_test2.jsonl` seguía siendo
  el del plan (`85883b11…`).
- Revisión del modelo (de la caché de Hugging Face del autor):
  `cambridgeltl/SapBERT-from-PubMedBERT-fulltext`, snapshot
  `090663c3ae57bf35ffe4d0d468a2a88d03051a4d`.
- Verificaciones de `dmb compare`: datos y splits iguales al freeze y umbrales de las corridas de dev
  congeladas, en las cinco etiquetas comparadas.
- Archivos: `test2/*.json`, `test2_comparison_sapbert.json` (pruebas pareadas contra la regresión
  logística con Wilson) y `test2_precision_at_coverage.json`.

## 1. test2 (2.000 productos, 175 no están en el catálogo)

| | Regresión logística, Wilson | SapBERT A (consulta completa), Wilson | SapBERT A, LTT | SapBERT B (consulta corta), Wilson | SapBERT B, LTT |
|---|---:|---:|---:|---:|---:|
| Acierto del primer candidato (en catálogo) | 84,1 % | 82,9 % | 82,9 % | 87,9 % | 87,9 % |
| Respuesta entre los cinco primeros | 92,3 % | 96,6 % | 96,6 % | 96,4 % | 96,4 % |
| Cobertura automática | 64,6 % | 44,45 % | 44,7 % | 40,5 % | 41,2 % |
| Precisión de lo aceptado (IC de Wilson 95 %) | 96,2 % (95,0–97,1) | 95,4 % (93,8–96,6) | 95,3 % (93,7–96,5) | 97,0 % (95,6–98,0) | 96,8 % (95,4–97,8) |
| Aceptaciones falsas (fuera del catálogo) | 49 (19) | 41 (23) | 42 (23) | 24 (5) | 26 (5) |
| ECE / Brier | 0,018 / 0,092 | 0,053 / 0,135 | 0,053 / 0,135 | 0,062 / 0,111 | 0,062 / 0,111 |

## 2. Hipótesis

### H11, SapBERT ordena mejor los candidatos: **se cumple**

El acierto del primer candidato de B fue 87,9 %, contra 84,1 % de la regresión logística: +3,8
puntos (IC bootstrap pareado 2,4 a 5,3; McNemar p < 0,001). En dev había sido +2,5. A, con la
consulta completa, quedó en 82,9 % (−1,2, IC −3,1 a 0,7; p = 0,23).

### H12, con control del riesgo SapBERT acepta menos productos sin revisión: **se cumple**

Con Wilson, la cobertura fue 44,45 % (A) y 40,5 % (B), contra 64,6 %: −20,15 puntos (IC −22,65 a
−17,6) y −24,1 (IC −26,4 a −21,8).

### H13, descriptiva

- **Precisión en test2:** las cuatro combinaciones quedan sobre 95 % (entre 95,3 % y 97,0 %).
- **Productos fuera del catálogo aceptados:** B aceptó 5 de 175, contra 19 de la regresión
  logística (McNemar p = 0,001); A aceptó 23 (p = 0,57).
- **Precisión de los productos con mayor puntaje**, según la cobertura:

  | Cobertura | 5 % | 10 % | 20 % | 40 % | 60 % |
  |---|---:|---:|---:|---:|---:|
  | Regresión logística | 100 % | 100 % | 98,8 % | 98,3 % | 97,0 % |
  | Gradient boosting (v0.2.0) | 97,0 % | 98,5 % | 99,3 % | 99,1 % | 97,7 % |
  | SapBERT A | 99,0 % | 99,0 % | 98,3 % | 96,5 % | 92,7 % |
  | SapBERT B | 100 % | 100 % | 99,5 % | 97,0 % | 95,3 % |

## 3. Exploratorio (no pre-registrado como hipótesis)

De los 1.825 productos de test2 con su concepto en el catálogo, la regresión logística y SapBERT B
aciertan juntos en 1.479; solo las reglas, en 56; solo SapBERT, en 125; ninguno, en 165. Es el
mismo patrón de dev: los dos métodos se complementan, y combinarlos queda para la Etapa 3.

## 4. Lectura para el artículo

1. SapBERT, con la consulta corta y los nombres de RxNorm, **ordena mejor** los candidatos que el
   generador basado en reglas: casi 4 puntos más en el primer candidato y 4 más entre los cinco
   primeros.
2. Pero su similitud **separa peor** lo que se puede aceptar solo: con la misma meta de 95 %, cubre
   entre 20 y 24 puntos menos. Las reglas fijan dosis y forma de manera explícita, y eso produce un
   puntaje más confiable en la parte alta.
3. SapBERT con la consulta corta acepta **muchos menos productos fuera del catálogo** (5 contra 19):
   en este benchmark, el error más difícil de ver en operación.
4. Las reglas con control del riesgo **funcionaron igual con otro modelo**: con Wilson y LTT, las
   cuatro configuraciones de SapBERT mantuvieron la precisión sobre 95 % en test2. El protocolo no
   depende del modelo de puntaje.
5. Los dos métodos aciertan en productos distintos; un sistema combinado es el paso natural.
