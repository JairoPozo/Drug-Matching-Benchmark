# Revisión farmacéutica de las aceptaciones falsas en test2: protocolo

Escrito el 2026-11-25, antes de enviar los casos al revisor y antes de ver cualquier respuesta.
Es un análisis adicional al pre-registro de la v0.2.0: no cambia H1 a H4, que se evaluaron con las
etiquetas oficiales y se reportan en `../resultados.md`.

## Objetivos

1. Estimar cuántas de las aceptaciones automáticas que contradicen la etiqueta oficial son errores
   reales para un farmacéutico, y qué tan graves son.
2. Detectar etiquetas oficiales (`openfda.rxcui`) que no corresponden al producto descrito.
3. Comparar la gravedad de los errores de la v0.2.0 con los de la línea base (etapa 5 con umbral
   de Wilson).

## Casos

- Los 86 productos de test2 que al menos uno de los dos métodos aceptó automáticamente con un
  concepto distinto de su etiqueta: 35 aceptados por ambos, 37 solo por la v0.2.0 y 14 solo por la
  línea base. En ningún producto los dos métodos aceptaron conceptos distintos entre sí.
- En 32 de los 86, el concepto de la etiqueta no está en el catálogo.
- Se generan con `scripts/pharmacist_review.py` (semilla 20261125), que escribe los casos ciegos y
  la clave en `data/review/revision_farmaceutica_test2/` (fuera de git).

## Ciego

- El revisor ve cada producto (campos del NDC y enlace a su ficha en DailyMed) y dos conceptos de
  RxNorm, "Concepto 1" y "Concepto 2", en orden aleatorio en cada fila. Las filas también van en
  orden aleatorio.
- No sabe cuál es la etiqueta oficial ni cuál eligió el sistema. Se le pide no usar la sección
  RxNorm de DailyMed para decidir.
- La clave queda solo con el autor hasta que lleguen las respuestas.

## Preguntas

1. ¿Son el mismo medicamento? Sí (equivalentes), No (distintos) o No se puede saber.
2. ¿Cuál describe el producto? Concepto 1, Concepto 2, Ambos, Ninguno o No se puede saber.
3. Gravedad si se confunden: Sin impacto, Baja, Media o Alta, con las definiciones de la hoja
   Instrucciones del Excel.
4. Comentario libre, opcional.

## Análisis previsto

Por método (v0.2.0 y línea base) y por grupo (solo v0.2.0, solo línea base, ambos):

1. Proporción de pares equivalentes (pregunta 1 = Sí): aceptaciones que la etiqueta cuenta como
   error pero que no lo son para un farmacéutico.
2. Proporción de casos en que el revisor elige el concepto aceptado y no el de la etiqueta
   (pregunta 2): posibles errores de etiqueta.
3. Distribución de la gravedad (pregunta 3) de los errores reales (pregunta 1 = No).
4. Secundario: precisión de lo aceptado en test2 recalculada contando como correctos los pares
   equivalentes, con su intervalo de Wilson. Se reporta junto a la precisión oficial, sin
   reemplazarla.

Todo es descriptivo, sin pruebas de hipótesis. "No se puede saber" se reporta aparte y no cuenta ni
como acierto ni como error. Si hay un segundo revisor, se reporta el acuerdo entre ambos en la
pregunta 1 (kappa de Cohen).

## Revisor

- [Nombre], químico farmacéutico, [institución]; fecha de la revisión.
- Con su consentimiento, aparece como coautor o en los agradecimientos del artículo.
