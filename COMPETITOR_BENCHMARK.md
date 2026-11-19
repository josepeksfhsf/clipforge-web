# ClipForge — referencias de producto y prioridades competitivas

Investigación: noviembre de 2026. Esta revisión solo utiliza funciones anunciadas públicamente; no replica código, marcas, diseño ni contenido de terceros.

## Comparación con herramientas del sector

| Producto | Funciones públicas pertinentes | Qué puede aprender ClipForge |
|---|---|---|
| OpusClip | Reencuadre inteligente, subtítulos, plantillas, edición manual, programación/publicación en distintas redes | Que el encuadre, la legibilidad y la edición del resultado importan tanto como seleccionar buenos momentos |
| Ssemble | Clips automáticos, captions, layouts Fill / Fit / Auto, edición y calendario | Facilitar varios encuadres y hacer claro cuándo un video será recortado |
| Miqla | Promueve clips únicos, nuevos encuadres, puntuación de atractivo y subtítulos | Mostrar variedad y explicar el puntaje, sin afirmarlo como probabilidad de éxito |

Fuentes del producto (verificar antes de tomar decisiones en el futuro):
- https://www.opus.pro/
- https://www.opus.pro/ai-reframe
- https://www.ssemble.com/features
- https://help.ssemble.com/docs/make-clips/how-to-reframe-a-clip-show-the-whole-video-or-move-the-crop
- https://miqla.app/

## Implementado en ClipForge
- Cantidad: 1 a 12 cortes sin solapamiento temporal, con análisis limitado por CPU.
- Resolución: 720 × 1280 o 1080 × 1920.
- Subtítulos automáticos opcionales (Whisper tiny; reconocimiento imperfecto en ruido).
- Voz robótica en español (eSpeak NG, no Loquendo comercial).
- Títulos/descripciones/hashtags sugeridos, revisables.
- Encuadre a elegir: recorte central, video completo con franjas, o video completo con fondo desenfocado. **No hay seguimiento inteligente de personas**, y no se debe anunciar como tal.
- Descarga individual MP4 y exportación ZIP.
- Publicación a YouTube solo tras OAuth y consentimiento; las otras redes necesitan permisos oficiales adicionales.
- Los planes anunciados son propuestas y no hay cobros activos.

## Prioridades — no comercializar hasta cumplirlas

**P0: fiabilidad y protección**
1. Persistencia de clips y base de datos con estados de trabajos; Render Free pierde archivos al reiniciar/desplegar.
2. Cuentas y autenticación con control de acceso a los MP4, protección por usuario y controles de borrado.
3. Cola real y aislamiento de recursos para múltiples clientes; evitar que un trabajo largo bloquee la plataforma.
4. Pruebas reales con 720p/1080p, opciones de encuadre, subtítulos y narración juntas.

**P1: edición y calidad visible**
1. Edición del comienzo/fin de cada clip sin regenerar el video completo.
2. Ajustes para legibilidad de subtítulos y estilos con vista previa.
3. Reencuadre asistido por cara/locutor (requiere investigación y rendimiento real; no prometer seguimiento actual).
4. Títulos y subtítulos revisables para corregir errores de reconocimiento.
5. Mejor selección: segmentar escenas, penalizar pausas y diálogos repetidos; validar con videos de varios géneros.

**P2: crecimiento y monetización**
1. Plantillas de marca y presets de relación de aspecto para podcasts, juegos y entrevistas.
2. Biblioteca de trabajos e historial, almacenamiento en la nube y parámetros reutilizables.
3. Publicación a Instagram/Facebook/TikTok solo tras consentimientos y aprobaciones.
4. Medir costo real por clip antes de vender planes; mantener precios y cupos que el propietario haya aprobado.
5. Material promocional propio y ejemplos antes/después verificados, sin promesas de viralidad.

## Regla para revisiones
No clonar interfaces, no utilizar el contenido de otros servicios como propio, no inventar medidas de viralidad. Cambios pequeños y comprobados antes de desplegar. Evitar despliegues cuando hay trabajos activos y no generar costos ni cobros sin autorización.
