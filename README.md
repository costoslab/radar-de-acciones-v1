# Radar de Acciones

Dashboard de valuación de acciones (P/E, CAPE, ciclo, contexto macro) basado en el
método de Roberto Ruarte. Universo curado de ~86 activos: panel líder BYMA, ADRs
argentinos, subyacentes de CEDEAR, y ETFs principales.

## Cómo funciona

`scripts/` contiene el pipeline completo en Python (sin dependencias externas más
allá de la librería estándar):

1. `build_dataset.py` — trae precio e historial (Yahoo Finance), EPS histórico (SEC
   EDGAR), macro EEUU (FRED) y macro Argentina (BCRA), calcula P/E, pseudo-CAPE y un
   proxy heurístico de ciclo por activo. Escribe `output/dataset.json`.
2. `make_compact.py` — genera una versión recortada del dataset para no inflar el
   HTML final. Escribe `output/dataset_compact.json`.
3. `render_dashboard.py` — inyecta el dataset compacto en `dashboard_template.html`
   y escribe `output/dashboard.html`, el dashboard final autocontenido.

## Automatización

`.github/workflows/refresh.yml` corre este pipeline todos los días a las 00:00 UTC
(21:00 hora Argentina) usando GitHub Actions — sin depender de ninguna PC ni sesión
de Claude. Si más del 17% de los activos (>15 de 86) fallan en una corrida, el
workflow aborta antes de publicar, para no pisar el dashboard con datos rotos.

El resultado se publica en GitHub Pages (rama `gh-pages`), en una URL pública que no
requiere ningún login para verse.

Para forzar una actualización fuera de horario: pestaña **Actions** de este repo →
"Actualizar Radar de Acciones" → **Run workflow**. Requiere estar logueado en GitHub
(no en Claude).

## Actualizar el código del pipeline

Si se edita cualquier archivo en `scripts/` (universo de activos, pesos del score,
lógica de cálculo, o el template HTML), el próximo refresco automático ya usa la
versión nueva — no hay ninguna copia duplicada que sincronizar a mano.
