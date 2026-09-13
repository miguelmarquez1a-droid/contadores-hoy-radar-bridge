# Puente externo – Radar Normativo de Contadores Hoy

Proyecto de GitHub Actions para consultar DIAN, CTCP y Presidencia–DAPRE cada seis horas y publicar un archivo JSON mediante GitHub Pages.

## Activación

1. Crear un repositorio público en GitHub.
2. Subir todos los archivos conservando la carpeta `.github/workflows/`.
3. Abrir **Settings > Pages** y elegir **GitHub Actions** como origen.
4. Abrir **Actions > Actualizar Radar Normativo > Run workflow**.
5. Verificar `https://USUARIO.github.io/REPOSITORIO/feed.json`.

## Integración con WordPress

La dirección pública de `feed.json` se agregará a Contadores Hoy – Radar Normativo cuando el repositorio esté publicado.

## Seguridad

El proyecto solo hace solicitudes GET a portales públicos. No requiere contraseñas, tokens ni secretos para ejecutarse en un repositorio público.
