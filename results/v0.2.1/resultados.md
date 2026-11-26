# Resultados de la v0.2.1: umbrales con garantía formal

Evaluación según el pre-registro (`plan.md`). Se reportan todas las hipótesis, se cumplan o no.

- Código: commit `91cb8a9`, etiqueta `v0.2.1-pretest`.
- Fecha: 2026-11-26 (UTC). Las cuatro etiquetas nuevas (`ltt` y `sgr` en los dos modelos) se
  evaluaron **una sola vez** en test2 (`reports/test_runs.log`). `wilson` no se volvió a evaluar: la
  comparación usa sus corridas de la v0.2.0.
- Verificaciones de `dmb compare`: los datos y splits coinciden con el freeze, las seis etiquetas
  usaron los umbrales congelados en dev y los coeficientes de la regresión logística son los
  congelados.
- Archivos: `test2/*.json` (métricas de las cuatro corridas nuevas), `test2_comparison_lr.json` y
  `test2_comparison_gb.json` (pruebas pareadas contra
  `wilson`), `resampling_dev_test2.json` (H7) y `resampling_dev.json` (el ensayo con dev).
- `<lr>` = `rules-stage5` (regresión logística); `<gb>` = `rules-dropexpected_form_missing-featuresv2-scorergb-stage5` (gradient boosting, la v0.2.0).

## 1. test2 (2.000 productos, 175 no están en el catálogo)

| | `<lr>` wilson | `<lr>` ltt | `<lr>` sgr | `<gb>` wilson | `<gb>` ltt | `<gb>` sgr |
|---|---:|---:|---:|---:|---:|---:|
| Umbral (fijado en dev) | 0,8285 | 0,823 | 0,8472 | 0,7895 | 0,784 | 0,8292 |
| Cobertura automática | 64,60 % | 64,80 % | 62,80 % | 72,55 % | 72,80 % | 70,35 % |
| Aceptados | 1.292 | 1.296 | 1.256 | 1.451 | 1.456 | 1.407 |
| Precisión de lo aceptado | 96,21 % | 96,06 % | 96,66 % | 95,04 % | 94,85 % | 95,52 % |
| Intervalo de Wilson 95 % | 95,0–97,1 | 94,9–97,0 | 95,5–97,5 | 93,8–96,0 | 93,6–95,9 | 94,3–96,5 |
| Aceptaciones falsas | 49 | 51 | 42 | 72 | 75 | 63 |
| … de productos que no están en el catálogo (de 175) | 19 | 19 | 17 | 28 | 29 | 26 |

## 2. Hipótesis

### H5, las reglas con garantía cumplen la meta en test2: **se cumple en 3 de 4 casos**

- `<lr>` con `ltt` (96,06 %), `<lr>` con `sgr` (96,66 %) y `<gb>` con
  `sgr` (95,52 %) quedan sobre 95 %.
- `<gb>` con `ltt` queda en **94,85 %** (1.381 correctas de 1.456): no se cumple. El plan lo
  anticipaba. `ltt` acepta 5 productos más que `wilson` (puntaje entre 0,784 y 0,7895): 2 correctos y
  3 incorrectos, uno de ellos de un producto que no está en el catálogo.
- Esto no contradice la garantía, que habla de la precisión en la población con probabilidad
  1 − δ y no de cada muestra. Juntando dev y test2, la precisión de `<gb>` con `ltt` en ese umbral es
  95,4 % (2.913 aceptados, 133 errores). Lo que mide la garantía es H7.
- `<gb>` baja de dev a test2 con todas las reglas (con `wilson`: 96,15 % en dev, 95,04 % en test2);
  `<lr>` no (96,2 % en ambos). Es consistente con que la v0.2.0 se eligió en dev.

### H6, costo de la garantía en test2 (descriptiva)

| Regla, modelo | Cobertura contra `wilson` (IC bootstrap 95 %) | Pasan a aceptarse (correctos) | Dejan de aceptarse (correctos) | No están en el catálogo y se aceptan (McNemar) |
|---|---:|---:|---:|---:|
| `ltt`, `<lr>` | +0,20 pts (+0,05 a +0,40) | 4 (2) | 0 (0) | 19 contra 19 (p = 1,00) |
| `sgr`, `<lr>` | −1,80 pts (−2,40 a −1,25) | 0 (0) | 36 (29) | 17 contra 19 (p = 0,50) |
| `ltt`, `<gb>` | +0,25 pts (+0,05 a +0,50) | 5 (2) | 0 (0) | 29 contra 28 (p = 1,00) |
| `sgr`, `<gb>` | −2,20 pts (−2,90 a −1,55) | 0 (0) | 44 (35) | 26 contra 28 (p = 0,50) |

- `ltt` solo mueve productos de revisión a aceptación, y `sgr` solo de aceptación a revisión. La
  banda de abstención no cambia.
- De lo que `sgr` deja de aceptar, cerca de 4 de cada 5 eran respuestas correctas: su margen extra
  sale caro en cobertura.

### H7a, la implementación respeta la garantía: **se cumple**

En el remuestreo (población de 4.000 productos de dev y test2, 360 que no están en el catálogo;
1.000 muestras de 2.000 con reemplazo), la tasa de violación (precisión de la población bajo 95 %
en el umbral elegido) es:

- `ltt`: 2,9 % en `<lr>` y 3,9 % en `<gb>` (error de Monte Carlo 0,5 y 0,6 pts).
- `sgr`: 0,4 % y 0,2 %.

Las cuatro quedan bajo 5 % (y bajo el 6,4 % que se habría leído como error de implementación).
Ninguna regla se quedó sin umbral en ninguna repetición.

### H7b, con qué frecuencia falla cada regla y cuánto cubre (descriptiva)

| Regla | Violación `<lr>` | Cobertura media `<lr>` (2,5–97,5) | Violación `<gb>` | Cobertura media `<gb>` (2,5–97,5) |
|---|---:|---:|---:|---:|
| `point` (v0.1.0) | 50,3 % | 67,8 % (64,7–70,0) | 48,7 % | 74,0 % (70,3–77,2) |
| `wilson` (v0.2.0) | 1,5 % | 64,3 % (59,5–67,9) | 1,5 % | 70,2 % (63,9–73,8) |
| `ltt` | 2,9 % | 64,8 % (60,5–68,4) | 3,9 % | 70,8 % (64,3–74,2) |
| `sgr` | 0,4 % | 62,4 % (53,2–66,3) | 0,2 % | 68,4 % (62,6–72,8) |
| `ltt` con δ = 0,025 | 1,2 % | 64,1 % (57,6–68,0) | 1,5 % | 70,1 % (63,9–73,9) |
| Mejor umbral de la población (referencia) | — | 68,0 % | — | 73,9 % |

- `wilson` acepta el mismo conjunto que `ltt` con δ = 0,025 en el 53,0 % de las repeticiones
  de `<lr>` y en el 40,5 % de las de `<gb>`; en el 37,1 % y el 49,6 % acepta más.
  Aun así falla casi con la misma frecuencia que ella (1,5 % contra 1,2 % y 1,5 %).

## 3. Lectura para el artículo

1. **La regla puntual falla la mitad de las veces** (50,3 % y 48,7 %), como se espera de un
   umbral puesto justo donde la estimación toca 95 %.
2. **La regla de Wilson se comporta como una regla con garantía.** No tiene garantía formal, pero
   falló en el 1,5 % de las muestras en los dos modelos, casi igual que `ltt` con
   δ = 0,025 (1,2 % y 1,5 %). Que a veces acepte más que ella no se tradujo en más fallas: en este benchmark, el
   problema de multiplicidad casi no se nota en la práctica.
3. **La garantía formal sale casi gratis.** `ltt` con δ = 0,05 cubre medio punto más que `wilson`
   en el remuestreo y 0,2 a 0,25 puntos más en test2, y su tasa de falla queda bajo δ. El costo:
   falla más cerca de δ (2,9–3,9 %), y por eso en una muestra concreta puede quedar justo bajo la
   meta, como `<gb>` en test2.
4. **`sgr` es la más conservadora**: falla menos de 0,5 % de las veces, pero cubre unos 2 puntos
   menos que `wilson`, por la corrección de su búsqueda binaria.
5. **Controlar el riesgo cuesta cobertura.** Con 2.000 productos de calibración, `wilson`, `ltt` y
   `sgr` quedan 3 a 6 puntos bajo el mejor umbral de la población, que solo se conoce sabiendo
   todas las respuestas.
6. Recomendación práctica: `ltt` cuando se necesita una garantía formal, con δ según el riesgo que
   se acepte; `sgr` solo si se necesita fallar casi nunca.
