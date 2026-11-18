# Conectar Instagram, TikTok y Facebook a ClipForge

Sitio: https://clipforge-web-dccq.onrender.com/#social-hub

## Estado actual

La conexión usa OAuth oficial: el usuario autoriza al proveedor y ClipForge recibe una sesión cifrada en cookie HttpOnly Secure. **Conectar NO da permisos para publicar.** La publicación directa desde el sitio permanece habilitada únicamente para YouTube. Las apps de ChatGPT y Metricool son independientes de ClipForge.

Los botones se activan cuando se configuran credenciales de desarrollador en Render, nunca en el frontend o el repositorio.

## Instagram

1. Abre https://developers.facebook.com/apps/ y crea/abre una aplicación con Instagram API con Instagram Login (Business Login).
2. Registra exactamente la redirección: https://clipforge-web-dccq.onrender.com/api/social/callback/instagram
3. En Render → clipforge-web → Environment define:
    - INSTAGRAM_CLIENT_ID: Instagram App ID del producto
    - INSTAGRAM_CLIENT_SECRET: Instagram App Secret del producto
4. Usa una cuenta profesional de Instagram (Empresa o Creador). Si la app está en modo desarrollo, registra la cuenta como tester/administrador.
5. La conexión usa el permiso instagram_business_basic. Publicar requiere el permiso adicional instagram_business_content_publish y la aprobación correspondiente.

## TikTok

1. En https://developers.tiktok.com/ crea una app y habilita Login Kit para Web.
2. Registra https://clipforge-web-dccq.onrender.com/api/social/callback/tiktok
3. En Render configura TIKTOK_CLIENT_KEY y TIKTOK_CLIENT_SECRET.
4. Cumple el registro de dominios y la revisión de Login Kit de TikTok.
5. La conexión usa solo user.info.basic. Para publicaciones directas se requiere la aprobación de video.publish y la Content Posting API, que aún no están implementadas en ClipForge.

## Facebook

1. En https://developers.facebook.com/apps/ habilita Facebook Login para Web o Facebook Login for Business.
2. Registra como Valid OAuth Redirect URI: https://clipforge-web-dccq.onrender.com/api/social/callback/facebook
3. En Render configura FACEBOOK_APP_ID y FACEBOOK_APP_SECRET (o META_APP_ID/META_APP_SECRET).
4. Registra tu usuario como administrador/desarrollador/tester si la app está en modo desarrollo.
5. ClipForge solicita pages_show_list para identificar las páginas que administra la cuenta; las publicaciones en páginas requieren permisos y una función de publicación adicional. Facebook no permite usar las APIs de páginas para publicar en perfiles personales.

## Comprobación

Guarda los cambios en Render con Save, deploy. Abre https://clipforge-web-dccq.onrender.com/#social-hub y comprueba cada botón.

Estado del servidor (sin secretos): https://clipforge-web-dccq.onrender.com/api/social/connections

Si aparece «Acceso bloqueado» comprueba la prueba/tester de la app, el producto activado, los permisos concedidos y la URI de retorno exacta. No compartas contraseñas, secretos, códigos OAuth ni tokens en el chat.

La sesión en navegador se guarda cifrada por separado para cada proveedor y cada visitante, con caducidad máxima de 25 días. Desconectar la cuenta de ClipForge borra su cookie; para revocar el permiso en el proveedor usa los ajustes de TikTok o Meta.

## Documentación oficial

- https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login/
- https://developers.facebook.com/docs/graph-api/guides/versioning/
- https://developers.tiktok.com/docs/en/login-kit-web
- https://developers.tiktok.com/docs/en/oauth-get-a-user-access-token
- https://developers.tiktok.com/docs/en/content-posting-api-get-started
