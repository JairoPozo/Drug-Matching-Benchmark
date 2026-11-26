# Pre-registro de la v0.2.0

Escrito y commiteado **antes** de cualquier experimento de la v0.2.0. Lo que está aquí no se cambia
después de ver resultados; si algo cambia, se agrega una sección "Desviaciones" con fecha y motivo.

- Punto de partida: etiqueta `v0.1.0` (resultados en `results/v0.1.0/`).
- Pregunta del trabajo: ¿se puede automatizar la identificación de medicamentos con un **control
  explícito del riesgo**, combinando conocimiento farmacéutico estructurado (RxNorm) con una
  probabilidad calibrada?

## 1. Datos y su uso

| Split | Productos | Uso en la v0.2.0 |
|---|---|---|
| train | 30.375 | Entrenar (tablas de formas, factores, modelos de puntaje). Solo filas cuyo concepto está en el catálogo. |
| dev | 2.000 (185 que no están en el catálogo) | Todos los experimentos, ablations y la selección de la configuración final. |
| test (v0.1.0) | 2.000 (182) | Solo histórico. No se usa para decidir nada de la v0.2.0. |
| **test2** | 2.000 (175) | Evaluación final de la v0.2.0, **una sola vez por configuración**. |

- `test2` se sacó del pool de train de la v0.1.0: un producto por grupo, en grupos que no tocan
  dev, test ni train (cero grupos compartidos), estratificado por tipo de producto con la mezcla
  global (47,2 % OTC, igual que dev y test), semilla 4242.
- Un primer borrador de `test2` usó la mezcla OTC del pool (54 %) y se descartó **antes de evaluar
  nada en él**, para que sea comparable con dev y test. Quedó archivado localmente.
- Hashes SHA-256 al pre-registrar (`dmb freeze` los volverá a verificar antes de la evaluación final):
  - `splits/test2.txt`: `2057ebdc9fdeb7cdca0b649c993cc80310bdb8fea2bc58ea15c7474c161ae5c6`
  - `splits/meta.json`: `d96dd7852a1a1d6643314de9824225ecf8a2c2460d1d0f992d6b00cd5edb3922`
- Nota de honestidad: las debilidades que se atacan (dentales, inhalados, productos que no están en
  el catálogo) se vieron en el test de la v0.1.0. También están en dev (los dentales ya eran débiles
  en dev desde la etapa 3), y toda decisión de la v0.2.0 se justifica solo con dev.

## 2. Línea base

El método de la v0.1.0 **re-entrenado con el train de la v0.2.0** (30.375 productos), porque el train
cambió al sacar `test2`:

- `rules-stage4`: reglas con pesos a mano.
- `rules-stage5`: mismos candidatos, regresión logística con cross-fitting.

Sus umbrales se fijan en dev con el mismo procedimiento de la v0.1.0 (precisión ≥ 95 % puntual).

## 3. Hipótesis y criterios de éxito (evaluados en test2)

Métrica principal: **cobertura automática** = productos aceptados solos / productos totales.

| | Hipótesis | Criterio de éxito en test2 |
|---|---|---|
| H1 | **Control explícito del riesgo.** Elegir el umbral en dev con el límite inferior de Wilson (95 %) de la precisión ≥ 95 %, en vez del valor puntual, hace que la precisión en datos nuevos cumpla la meta. | La precisión de las aceptaciones de la v0.2.0 en test2 es ≥ 95 %. Se reporta también su intervalo de Wilson. |
| H2 | **Más cobertura con el mismo riesgo.** | La cobertura de la v0.2.0 supera a `rules-stage5` re-entrenado **con el mismo criterio de umbral que H1**, y el intervalo bootstrap pareado (95 %) de la diferencia excluye 0. |
| H3 | **Menos productos inexistentes aceptados.** | Menos aceptaciones sobre productos que no están en el catálogo que `rules-stage5` re-entrenado (mismo criterio de umbral), sin incumplir H2. |
| H4 | **Debilidades por categoría.** | Se reportan acierto top 1 y tasa de aceptaciones falsas en dentales, inhalados y kits, contra la línea base. Es descriptiva: se informa aunque no mejore. |

Para que H2 y H3 comparen solo el método (y no el umbral), la línea base también se evalúa con el
umbral de H1. La comparación con umbral puntual se reporta aparte.

## 4. Experimentos permitidos (solo en dev)

Presupuesto: **dos jornadas de trabajo**. Lo que no quepa queda para la Etapa 3.

1. Ablations: sacar cada atributo del modelo y cada etapa de reglas; medir su aporte en dev.
2. Atributos nuevos: base de la concentración desde los atributos de RxNorm (dentales), señales de
   "no está en el catálogo" (por ejemplo, ningún candidato con dosis exacta), atributos de vía.
3. Método de puntaje alternativo: gradient boosting (scikit-learn) contra regresión logística.
4. Umbral con control de riesgo (H1).
5. Análisis de errores por categoría, automatizado.

Fuera de alcance de la v0.2.0: embeddings y LLMs (Etapa 3 del plan).

## 5. Regla de selección (fijada ahora)

Entre las configuraciones probadas en dev, la v0.2.0 es la de **mayor cobertura en dev con el
límite inferior de Wilson de la precisión ≥ 95 %**. Empate (menos de 0,5 puntos de cobertura): la
de menos aceptaciones de productos que no están en el catálogo; si persiste, la más simple.

Va **una sola configuración** de la v0.2.0 a test2 (más las dos líneas base). Así se evita probar
muchas variantes en test2 y quedarse con la mejor.

## 6. Evaluación final y reporte

1. `dmb freeze --version v0.2.0` con umbrales, coeficientes y hashes; commit y etiqueta
   `v0.2.0-pretest`.
2. Una corrida en test2 por configuración: `rules-stage4` y `rules-stage5` re-entrenados, y la v0.2.0.
3. `dmb compare --split test2`: Wilson, McNemar y bootstrap pareado.
4. Se reportan **todas** las hipótesis, se cumplan o no, y todas las configuraciones probadas en dev
   (tabla de ablation completa), no solo la elegida.
5. Opcional, como secundario: la v0.2.0 evaluada una vez en el test de la v0.1.0, sin usarlo para
   decidir nada.

## Enmiendas y desviaciones

### Regla

- Todo cambio a este plan se agrega aquí, con fecha, qué cambia, por qué y **qué datos se habían
  visto** en ese momento: ninguno, dev o test2. El texto original nunca se reescribe.
- Una enmienda hecha antes de cualquier experimento de la v0.2.0 mantiene el carácter
  confirmatorio de las hipótesis.
- Un cambio hecho después de ver resultados de dev se reporta como **exploratorio**.
- Un cambio hecho después de ver test2 quita el carácter confirmatorio a las hipótesis afectadas;
  se reporta así, y confirmarlas requeriría otro split independiente (por ejemplo, un test temporal
  con una descarga futura del NDC).

### Enmienda 1 (2026-11-25), antes de cualquier experimento de la v0.2.0

Datos vistos al hacerla: ninguno de la v0.2.0 (no hay corridas con el train nuevo en dev ni ninguna
en test2). Todos los cambios son aditivos; ningún criterio se relaja.

1. **H1: selección y resultado se separan.**
   - *Selección, en dev:* entre los umbrales posibles, el de mayor cobertura cuyo límite inferior
     de Wilson (95 %) de la precisión de aceptación sea ≥ 95 %. Se implementa como opción de la
     evaluación, `--threshold-rule wilson`, sin tocar los matchers; la regla actual (precisión
     puntual ≥ 95 %) se llama `point`.
   - *Resultado, en test2:* precisión observada, intervalo de Wilson del 95 %, número de
     aceptaciones automáticas y número de falsos positivos (y cuántos son productos que no están en
     el catálogo). El criterio de éxito no cambia: precisión observada ≥ 95 %. Cumplir en dev no
     garantiza cumplir en test2; si no se cumple, se reporta como resultado negativo.
2. **H2: de dónde viene la cobertura.** Además de la diferencia, se reporta: la diferencia absoluta
   en puntos porcentuales con su intervalo bootstrap pareado del 95 % sobre los mismos 2.000
   productos; cuántos productos pasan de revisión o abstención a aceptación, y cuántos de ellos son
   correctos; cuántos dejan de aceptarse; y la matriz completa de transiciones entre bandas.
3. **H3: tasa sobre los productos inexistentes.** Se reporta
   FAR_NIL = productos que no están en el catálogo y fueron aceptados / total de ellos en test2
   (175), con su diferencia pareada (bootstrap) y la prueba de McNemar sobre esos 175, además del
   conteo. Así se distingue una mejora real de una simple baja de cobertura.
4. **H4: solo descriptiva.** Dentales, inhalados y kits se reportan con su n en test2, acierto top 1
   y tasa de aceptaciones falsas, sin pruebas de hipótesis ni valores p.
5. **Trazabilidad.**
   - Datos: hash combinado `409a07a7755e3a7eb8b77ce98a88cae8e1c22173857410b4e92075c6b03bf436`;
     hashes por archivo y de las fuentes crudas (fecha y SHA-256 de NDC y RxNorm) en
     `results/v0.2.0/prereg_hashes.json`.
   - Splits: `test2.txt` y `meta.json` con los mismos hashes del pre-registro original; `dev.txt` y
     `test.txt` idénticos a la v0.1.0.
   - Código de la línea base: etiqueta `v0.1.0` (commit `fb0a744`). Lo agregado después (test2,
     comparación) no toca matchers, formas, dosis, lectura ni métricas; se verifica con
     `git diff v0.1.0 -- src/dmb/matchers src/dmb/forms.py src/dmb/strength.py src/dmb/parse.py
     src/dmb/rxvocab.py src/dmb/metrics.py` (salida vacía al hacer esta enmienda).
   - Pre-registro: commit `7f78279`, etiqueta `v0.2.0-prereg`. Esta enmienda: su propio commit,
     etiqueta `v0.2.0-prereg-a1`.
   - Selección: sección 5, con la regla de umbral de H1.
   - Evaluación final, comandos exactos (`<v020>` es la configuración elegida en dev):

     ```
     dmb freeze --version v0.2.0 --matcher rules-stage4 --matcher rules-stage5 \
       --matcher rules-stage5@wilson --matcher <v020>
     dmb eval --matcher rules --param stage=4 --split test2 --final
     dmb eval --matcher rules --param stage=5 --split test2 --final
     dmb eval --matcher rules --param stage=5 --threshold-rule wilson --split test2 --final
     dmb eval <v020> --threshold-rule wilson --split test2 --final
     dmb compare --split test2 --version v0.2.0 --matcher rules-stage4 --matcher rules-stage5 \
       --matcher rules-stage5@wilson --matcher <v020>
     ```

     La comparación de H2 y H3 es el último par: `<v020>` contra `rules-stage5@wilson`.
   - El chequeo de hashes de `results/v0.1.0/freeze.json` falla ahora en los archivos de train, como
     es esperable: la v0.1.0 se reproduce desde su etiqueta.

### Desviación 1 (2026-11-25), después de los experimentos en dev, antes de evaluar test2

Datos vistos: dev (jornadas 1 y 2). test2: nada.

- **Qué cambia:** la verificación de que la línea base es el método de la v0.1.0. La Enmienda 1 la
  definía como `git diff v0.1.0` vacío en los módulos de las reglas. Durante la v0.2.0 se
  agregaron a `rules.py` y `forms.py` opciones nuevas, todas desactivadas por defecto (atributos
  v2, gradient boosting, parámetros de ablation), así que el diff ya no está vacío.
- **Verificación que la reemplaza (más fuerte):** el código de la etiqueta `v0.1.0`, extraído con
  `git archive v0.1.0 src` y corrido sobre los mismos datos de la v0.2.0 en una carpeta aparte,
  produce en dev **predicciones idénticas** a las líneas base de la v0.2.0: `rules-stage4`, las
  mismas 6.216 filas (candidato, orden y puntaje); `rules-stage5`, los mismos candidatos y una
  diferencia máxima de puntaje de 0,0.
- **Efecto en las hipótesis:** ninguno. No cambia criterios, regla de selección ni la evaluación
  en test2.
