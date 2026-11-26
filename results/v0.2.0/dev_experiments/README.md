# Experimentos de la v0.2.0 en dev: jornada 1 (2026-11-25)

Solo dev (2.000 productos, 185 que no están en el catálogo) y el train de la v0.2.0 (30.375
productos). Ningún test se usó. Los JSON de esta carpeta tienen todas las cifras; se reportan
**todas** las configuraciones probadas, no solo las que funcionaron.

Cobertura = productos aceptados solos / 2.000. "Wilson" = umbral elegido con el límite inferior
de Wilson (95 %) de la precisión ≥ 95 % (H1). Diferencias pareadas: bootstrap de 2.000 remuestreos
sobre los mismos productos, intervalo del 95 %.

## Líneas base re-entrenadas (corridas oficiales `dmb eval` en dev)

| Configuración | Cobertura (umbral puntual) | Cobertura (Wilson) | Precisión (Wilson) | Inexistentes aceptados (Wilson) | ECE |
|---|---|---|---|---|---|
| `rules-stage4` (pesos a mano) | 52,0 % | 38,0 % | 96,6 % | 4 | 0,087 |
| `rules-stage5` (regresión logística) | 68,2 % | 64,7 % | 96,2 % | 23 | 0,021 |

La caché de experimentos reproduce exactamente estas cifras.

**Hallazgo 1.** Exigir la garantía de Wilson le cuesta 14 puntos de cobertura a la etapa 4 y solo
3,5 a la etapa 5: con un puntaje calibrado, el control de riesgo es mucho más barato.

## Método de puntaje (mismos candidatos, todos los atributos)

| Puntaje | Acierto top 1 | Cobertura (Wilson) | Inexistentes aceptados | ECE |
|---|---|---|---|---|
| Regresión logística | 85,7 % | 64,7 % | 23 | 0,021 |
| Gradient boosting (`HistGradientBoostingClassifier`) | 87,0 % | 72,4 % | 28 | 0,022 |

Gradient boosting contra regresión logística: cobertura **+7,6 puntos (6,2 a 9,0)**; tasa de
inexistentes aceptados +2,7 puntos (−0,5 a 5,9), no concluyente pero en contra de H3.

## Ablation de atributos (regresión logística, quitando uno a la vez)

Cobertura con umbral Wilson; base 64,7 %.

| Sin el atributo | Cobertura (Wilson) | Inexistentes aceptados | ECE |
|---|---|---|---|
| `heuristic_gap` (margen sobre el segundo) | **55,8 %** | **8** | 0,036 |
| `log_candidates` | 63,2 % | 23 | 0,031 |
| `sim` (similitud de texto) | 63,8 % | 21 | 0,026 |
| `is_top` | 64,1 % | 23 | 0,062 |
| `full`, `frac`, `converted`, `form_rel`, `form_unseen`, `n_ingredients`, `heuristic` | 64,6 a 64,8 % | 23 | 0,020 a 0,024 |
| `form_logp` | 66,2 % | 21 | 0,032 |
| Solo `heuristic` (etapa 4 calibrada) | 38,0 % | 4 | 0,146 |

- **Hallazgo 2.** El margen sobre el segundo candidato es el atributo central: sin él la cobertura
  cae 8,9 puntos (−10,6 a −7,1). Pero también explica la mayoría de los inexistentes aceptados (de
  23 a 8; −8,1 puntos de tasa, −12,4 a −4,3): cuando el producto no está en el catálogo, el
  candidato más cercano igual puede sacar un margen claro. El margen mide confianza **relativa**;
  detectar inexistentes requiere señales de calidad **absoluta** del calce.
- **Hallazgo 3.** La similitud de texto aporta poco pero no cero: −0,9 puntos de cobertura al
  quitarla (−1,4 a −0,5).
- Varios atributos de dosis y forma son redundantes entre sí: quitar uno solo no cambia nada,
  porque otro lleva la misma información.

## Ablation de componentes de las reglas

| Configuración | Acierto top 1 | Cobertura (Wilson), RL / GB | Inexistentes aceptados, RL / GB |
|---|---|---|---|
| Completa | 85,7 % | 64,7 % / 72,4 % | 23 / 28 |
| Sin el filtro de forma (los atributos de forma quedan) | 86,0 % | 63,6 % / 70,9 % | 21 / 26 |
| Sin las conversiones de dosis | 84,7 % | 62,9 % / 68,3 % | 18 / 25 |

- Con atributos de forma en el modelo, el filtro duro de forma aporta poco (alrededor de 1 punto) y
  a veces descarta la respuesta correcta.
- Las conversiones aportan 1 punto de acierto y de 2 a 4 de cobertura.

## Para la jornada 2

- Atributos de calidad absoluta del calce, para bajar los inexistentes aceptados (H3) sin perder
  la cobertura del gradient boosting.
- Base de la concentración para dentales (atributos BOSS de RxNorm).
- Análisis de errores por categoría.
- Selección final con la regla pre-registrada.

---

# Jornada 2 (2026-11-25): atributos de calidad absoluta, selección y errores

## Por qué se aceptaban productos inexistentes

En dev, con gradient boosting y atributos v1, se aceptaban 28 productos que no están en el catálogo.
En **20 de ellos la dosis calzaba pero la forma correcta no existía en el catálogo**, y el modelo
aceptaba la forma "hermana" (loción en vez de jabón medicado, Injection en vez de Cartridge,
solución en vez de suspensión). Causa: la verosimilitud de forma se medía **relativa a los otros
candidatos**, así que la mejor forma disponible parecía perfecta aunque no fuera la esperada.
Otros casos: calificativos del nombre que la consulta no menciona ("Abuse-Deterrent", "Weight
Management") y volúmenes de unidad distintos.

## Atributos v2 (calidad absoluta), opcionales: `--param features=v2`

`form_rel_global` (forma relativa a la esperada entre todas las formas), `expected_form_missing`
(la forma esperada no existe para ese conjunto de ingredientes), `qualifier_mismatch`,
`has_quantity`, `quantity_match`. La línea base v1 no cambia.

| Configuración (umbral Wilson) | Acierto top 1 | Cobertura | Inexistentes aceptados | ECE |
|---|---|---|---|---|
| Regresión logística, v1 | 85,7 % | 64,7 % | 23 | 0,021 |
| Regresión logística, v2 | 86,0 % | 67,0 % | 23 | 0,027 |
| Gradient boosting, v1 | 87,0 % | 72,4 % | 28 | 0,022 |
| Gradient boosting, v2 | 86,8 % | 70,9 % | 23 | 0,017 |
| Gradient boosting, v2 sin `expected_form_missing` | 87,4 % | 72,7 % | 27 | 0,025 |

Las ablations de cada atributo v2 están en `v2.json`.

## Dentales: investigado, sin arreglo con los datos permitidos

RxNorm tiene para el mismo fluoruro de sodio conceptos de 0,0015 y de 0,0024 MG/MG, ambos con base
"moiety", y las etiquetas de la FDA los asignan de forma inconsistente. No hay una conversión
estable ni un atributo de RxNorm que la resuelva. H4 queda descriptiva, como estaba previsto.

## Selección (regla pre-registrada, aplicada sin cambios)

`dmb experiment --select` sobre las 50 filas evaluadas en dev, que corresponden a 34 configuraciones
distintas porque algunas se repiten entre archivos (`selection.json`; corregido: antes decía 82):

- Mayor cobertura con Wilson ≥ 95 %: 72,7 % (gradient boosting, v2 sin `expected_form_missing`).
- Empate (menos de 0,5 puntos): gradient boosting v1 con 72,35 % (dos filas idénticas: `base` y
  `v2`).
- Desempate por menos inexistentes aceptados: 27 contra 28.
- **Elegida: `rules --param stage=5 --param scorer=gb --param features=v2 --param
  drop=expected_form_missing`, con `--threshold-rule wilson`.**

Las diferencias entre las primeras configuraciones están dentro del ruido de dev; la regla las
resuelve de forma determinista, que es para lo que se fijó de antemano.

Evaluación oficial en dev (reproduce la caché): acierto top 1 87,4 %, top 5 93,9 %, cobertura
72,7 % con precisión 96,1 %, 27 inexistentes aceptados (de 185), ECE 0,025, Brier 0,071.

## Análisis de errores por categoría (dev, umbral Wilson)

| Categoría | Línea base `rules-stage5@wilson` | Elegida |
|---|---|---|
| Acierto aceptado automáticamente | 1.245 | 1.398 |
| Acierto enviado a revisión | 310 | 188 |
| Inexistente correctamente no aceptado | 162 | 158 |
| Error aceptado: forma o variante elegida mal | 16 | 27 |
| Error aceptado: dosis no calza | 10 | 2 |
| Inexistente aceptado: forma hermana | 15 | 22 |
| Inexistente aceptado: otra diferencia | 8 | 5 |
| Error en revisión: forma o variante | 98 | 64 |
| Error en revisión: ingredientes distintos | 55 | 55 |
| Error en revisión: dosis no calza | 52 | 52 |
| Error en revisión: kit sin dosis | 29 | 29 |

- La mejora viene de **aceptar con confianza aciertos que antes iban a revisión** (+153).
- El riesgo residual es la **forma hermana**: el principal tipo de error aceptado y de inexistente
  aceptado.
- 136 errores no dependen del puntaje sino de la **generación de candidatos** (ingredientes, dosis,
  kits): no cambian con ningún modelo de puntaje. Son el objetivo natural de la Etapa 3
  (embeddings y LLMs).

Por vía, en dev (aceptaciones falsas, línea base → elegida): dentales 44,4 % → 10,0 %; inhalados
16,7 % → 0 %; tópicos 5,6 % → 7,6 %; inyectables 5,3 % → 6,4 %; orales 2,2 % → 1,9 %.

## Verificación de la línea base

El código de la etiqueta `v0.1.0`, corrido sobre los datos de la v0.2.0, produce en dev
predicciones idénticas a `rules-stage4` y `rules-stage5` de la v0.2.0 (mismos candidatos, mismo
orden, diferencia máxima de puntaje 0,0). Ver la Desviación 1 en `../plan.md`.
