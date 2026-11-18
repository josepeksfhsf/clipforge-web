# Publicación directa de Shorts desde ClipForge

## Estado real

- **YouTube:** integración de OAuth 2.0 + subida reanudable implementada. Se habilita una vez configuradas las credenciales oficiales.
- **TikTok / Instagram / Facebook:** ClipForge ofrece textos, hashtags y publicación asistida; la publicación directa todavía requiere configurar permisos y aprobar aplicaciones de cada plataforma. **No se publican videos desde ClipForge en esas redes todavía.**
- **Metricool:** las cuentas que conectes en Metricool no se transfieren automáticamente a ClipForge. La API de Metricool para integrar un sitio externo requiere un plan Advanced o Custom.

## Conectar YouTube de forma segura (una sola vez)

1. Abre [Google Cloud Console](https://console.cloud.google.com/). Crea o selecciona un proyecto en el que tengas permisos de edición.
2. Ve a **APIs & Services > Library** y habilita **YouTube Data API v3**.
3. Configura la pantalla de consentimiento de Google. Si la app está en modo prueba, añade tu propio correo como usuario de prueba. Solicita solo el alcance `https://www.googleapis.com/auth/youtube.upload`.
4. En **Credentials > Create Credentials > OAuth client ID**, elige **Web application** y agrega como **Authorized redirect URI**:

   `https://clipforge-web-dccq.onrender.com/api/publish/youtube/callback`

5. Copia el **Client ID** y el **Client secret** a las variables de entorno privadas de tu servicio [ClipForge en Render](https://dashboard.render.com/web/srv-dbur7lh5efls73f7042g):

   `YOUTUBE_CLIENT_ID` → ID del cliente OAuth de tipo Web
   `YOUTUBE_CLIENT_SECRET` → Secreto de ese cliente

   **No coloques el secreto en GitHub, HTML, mensajes públicos ni parámetros de URL.** El servicio ya tiene una clave privada de cifrado `SOCIAL_COOKIE_KEY` configurada de forma segura en Render; no debes cambiarla salvo que quieras invalidar las conexiones existentes.

6. Cuando Render haya actualizado el servicio, abre [ClipForge](https://clipforge-web-dccq.onrender.com/#social-hub), ve a **Redes sociales > Conectar YouTube con Google**, revisa los permisos y aprueba la conexión con tu cuenta.
7. Genera un Short, pulsa **Crear texto para publicar**, revisa título y descripción; en **Publicar en YouTube** elige visibilidad (por defecto *Privado*), indica si está dirigido a niños y si contiene material sintético realista, confirma que tienes los derechos y pulsa **Publicar en YouTube desde ClipForge**.
8. ClipForge sube el MP4 con la API oficial, y entrega el enlace tras recibir el ID de YouTube. YouTube puede continuar procesando el video una vez recibido.

## Publicación con los nuevos botones

Después de autorizar tu cuenta de Google, la interfaz ofrece tres formas:

1. **▶ Publicar en YouTube**, debajo de cada clip generado: selecciona ese clip y genera su título y descripción. El panel de YouTube permite revisar visibilidad, contenido para niños y contenido sintético antes de confirmarlo.
2. **🚀 Publicar todos los Shorts en YouTube**, debajo del conjunto de resultados: confirma una sola vez los ajustes y ClipForge prepara títulos y descripciones para todos y los envía de forma secuencial.
3. **🚀 Subir automáticamente mis Shorts a YouTube**, en el formulario antes de generar: marca la opción, selecciona privacidad (por defecto privada), responde las preguntas sobre público infantil y medios sintéticos, y confirma la autorización. Cuando termina de generar, la página inicia la publicación de todos los clips automáticamente. **Mantén abierta la pestaña hasta que empiece la subida**; después el servidor continúa mientras la instancia de Render esté activa.

El estado y los enlaces de cada subida aparecen en la sección de resultados. La publicación puede fallar por cuota de API, revisión de la app de Google, permisos insuficientes o reinicio del servicio; no se publica sin autorización. No relances un lote parcialmente completado sin revisar antes en YouTube Studio para evitar duplicados.

## Qué NO hace esta versión

- No se salta verificaciones antibots de YouTube ni descarga videos privados o no autorizados.
- No programa publicaciones para fechas futuras ni vuelve a intentarlo automáticamente si Render se reinicia; el plan Free utiliza almacenamiento temporal.
- No publica en TikTok, Instagram o Facebook sin permiso de las APIs respectivas.
- No promete viralidad ni garantiza la difusión de los Shorts.
- No usa contraseñas de Google, Instagram, Facebook o TikTok en formularios.

## Seguridad

- OAuth con estado antifalsificación, PKCE y alcance limitado a `youtube.upload`.
- Tokens cifrados en cookies `HttpOnly`, `Secure` y `SameSite=Lax`. No se guardan en el navegador mediante JavaScript ni en el disco temporal.
- Acciones de publicación protegidas con verificación de origen y token CSRF; subir es una decisión explícita.
- Los archivos se transmiten a Google en bloques de 4 MiB para evitar cargar un Short entero en RAM.
- Un cookie de conexión puede expirar: si falla la sesión, vuelve a conectar tu cuenta. Desconectar desde ClipForge borra la conexión local; para revocar por completo el permiso, visita [tu cuenta de Google](https://myaccount.google.com/permissions).

## Referencias oficiales

- [YouTube OAuth](https://developers.google.com/youtube/v3/guides/authentication)
- [YouTube videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert)
- [YouTube subida reanudable](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
- [TikTok Direct Post](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post)
- [Instagram API](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)
- [Metricool API](https://help.metricool.com/es/guia-basica-para-la-integracion-con-la-api-r97af)
