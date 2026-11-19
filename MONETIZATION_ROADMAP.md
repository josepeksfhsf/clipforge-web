# ClipForge: monetización y lanzamiento (propuesta beta)

Estado: planificación; aún no se cobran suscripciones ni hay funciones de pago habilitadas.

## 1. Estabilidad ANTES de cobrar

Completado o implementado:
- Generación de 1 a 12 Shorts con opciones 720p y 1080p.
- Subtítulos y narración robótica opcionales.
- Sugerencia de título, descripción y hashtags (no garantizan viralidad).
- Exportar todos los clips de un trabajo en ZIP hasta 350 MB.
- Avisar cuántos clips caben por duración del archivo seleccionado.
- Explicar al usuario si un trabajo se pierde por un reinicio o despliegue.

Pendiente y requisito del lanzamiento:
- Mover los videos de Render Free a almacenamiento objeto privado y persistente, con eliminación y URLs firmadas.
- Guardar trabajos y usuarios en una base de datos duradera. El estado local se pierde al sustituir la instancia de Render.
- Cola persistente para sobrevivir a reinicios, reintentos idempotentes, límites de procesamiento y métricas.
- Pruebas de generación de videos de 5, 30 y 60 minutos, con y sin IA/subtítulos.
- Probar carga simultánea y capacidad del servidor; establecer soporte y monitoreo de errores.

## 2. Cuentas y excepción gratuita para el dueño

- Implementar inicio de sesión seguro y cuentas verificadas.
- Configurar rol OWNER en el backend para el ID verificado del propietario: no paga ninguna suscripción.
- No usar un botón, un código en el frontend, correo escrito manualmente ni acceso anónimo para decidir quién es el dueño.
- La gratuidad para el dueño no exime los límites físicos de procesamiento necesarios para evitar caídas.
- Gestionar consumo, cuotas, historial, eliminaciones y estado de facturación por cuenta.

## 3. Planes propuestos, aún NO a la venta

| Plan | Precio tentativo | Cupo propuesto | Funciones |
| --- | --- | --- | --- |
| Gratis | CLP $0 | 1 clip/semana | 720p, videos hasta 5 min, futura marca de agua |
| Creator | CLP $7.990/mes | 30 clips/mes | 720p/1080p, subtítulos y voz, origen hasta 30 min |
| Pro | CLP $16.990/mes | 90 clips/mes | 1080p, 12 clips/trabajo, publicación YouTube autorizada |
| Estudio | CLP $37.990/mes | 200 clips/mes | Bibliotecas, lotes, colaboración (pendientes de construir) |
| Propietario | CLP $0 | Exento de cuota comercial | Acceso al plan máximo mediante cuenta verificada |

Los cupos se redujeron moderadamente respecto de la primera propuesta (noviembre 2026). Precios propuestos reajustados moderadamente tras verificar disponibilidad básica del sitio el 19 de noviembre de 2026; siguen sin cobros activos. Los precios y cuotas son hipótesis. Un plan de cientos de clips puede no ser rentable en Render Free: medir CPU por minuto, costo de almacenamiento, ancho de banda, transcripción, proveedor de pagos, impuestos, soporte y margen antes de publicarlo como oferta real.

## 4. Facturación segura

- Elegir proveedor de pagos compatible con el país y la empresa después de verificar costos y requisitos.
- Checkout oficial, webhooks con firma validada, suscripción activa SOLO cuando el proveedor confirme cobro.
- Cancelación sencilla, recibos/facturación según la jurisdicción, devoluciones, términos y privacidad.
- Plan de usuario y autorización verificadas del lado servidor; no permitir cambios por parámetros del navegador.
- Nunca almacenar tarjetas ni credenciales financieras en ClipForge.

## 5. Distribución y promoción

**Primero beta cerrada:** 10 a 20 creadores, streamers o editores prueban con material propio; medir éxito en la primera exportación, tiempo por video y errores. Resolver los bloqueos.

**Después beta pública:** video corto demostrativo, ejemplos reales "video largo a Shorts", compartir la web, tutoriales y comparaciones honestas. Sin comprar vistas ni inventar reseñas.

**Después suscripciones:** iniciar cuando se pueda cobrar, servir, cancelar, descargar y conservar videos de forma fiable; usar publicación consentida en redes.

**Métricas:** tasa de primera exportación, error por tipo de video, costo por clip, exportación en 720p/1080p, uso en 7 días, conversiones a planes y cancelaciones.

## Integraciones sociales

YouTube tiene rutas de publicación con autorización OAuth. Instagram, TikTok y Facebook tienen rutas de conexión, pero requieren credenciales de desarrollador y permisos adicionales de publicación. El consentimiento dentro de ChatGPT o Metricool no se puede transferir a ClipForge.

## Importante

Monetizar ClipForge es vender el **servicio de edición**, no prometer monetización o viralidad de los videos de los clientes. El ingreso de sus canales depende de las políticas y criterios de cada plataforma.
