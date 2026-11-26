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
