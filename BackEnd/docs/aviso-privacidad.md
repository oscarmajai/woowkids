# Aviso de privacidad (LFPDPPP)

El sistema trata datos de menores, la imagen de la INE del tutor y fotografías. La
Ley Federal de Protección de Datos Personales en Posesión de los Particulares (DOF
20-03-2025) exige ponerle al tutor un aviso de privacidad a su disposición y dejar
constancia de su consentimiento. Esto se implementó en la migración 107.

> **El texto sembrado es una plantilla.** Antes de usarlo con clientes, un abogado
> debe revisarlo y adaptarlo, y el AdministradorSistema debe capturar los datos reales
> del responsable.

## Datos

- `avisos_privacidad`: una fila por versión con el texto integral, el texto
  simplificado, los datos del responsable, los plazos de conservación, `vigente_desde`
  y `publicado_por`. La vigente es la de `version` más alta. Nunca se edita una
  versión publicada: publicar crea la siguiente.
- `registros.aviso_privacidad_version`, `aviso_privacidad_aceptado_en` y
  `acepta_finalidades_secundarias`: qué versión aceptó el tutor en el check-in, cuándo y
  si aceptó las finalidades voluntarias (lealtad y promociones). Son nulas en los
  registros anteriores a la migración 107.

Los textos llevan marcadores `{{razon_social}}`, `{{nombre_comercial}}`,
`{{domicilio}}`, `{{area_datos_personales}}`, `{{correo_datos_personales}}`,
`{{telefono_datos_personales}}`, `{{url_aviso}}`, `{{dias_conservacion_imagenes}}`,
`{{anios_conservacion_registros}}`, `{{version}}` y `{{fecha_vigencia}}`. La API los
reemplaza con los datos de la misma versión. Un dato vacío se muestra como
«[Pendiente de configurar: …]». Formato: `# ` título, `## ` sección, `- ` viñeta,
párrafos separados por una línea en blanco.

## API

| Método | Ruta | Acceso | Qué hace |
|---|---|---|---|
| GET | `/api/privacidad/aviso` | Público | Versión vigente con los marcadores ya reemplazados. |
| GET | `/api/privacidad/admin/aviso` | AdministradorSistema | Plantillas, datos del responsable, marcadores, datos pendientes e historial. |
| POST | `/api/privacidad/admin/aviso` | AdministradorSistema | Publica una versión nueva (201). `version_base` debe ser la vigente (si no, 409). Sin textos, conserva los vigentes. Un marcador inexistente da 422. |

`POST /api/estancias` (check-in normal y de invitados de evento) acepta además:

- `aceptaAvisoPrivacidad` (bool) y `versionAvisoPrivacidad` (int). Si falta la
  aceptación, responde 422 `AVISO_PRIVACIDAD_NO_ACEPTADO`. Si la versión ya no es la
  vigente, responde 422 `AVISO_PRIVACIDAD_DESACTUALIZADO`. En los dos casos no se guarda
  nada (ni se leen la INE o las fotos).
- `aceptaFinalidadesSecundarias` (bool, `true` por defecto: consentimiento tácito, art.
  7). Con `false`, el registro no acumula puntos y no puede canjearlos (422
  `LEALTAD_RECHAZADA`).

## Pendiente

- Datos reales del responsable y revisión legal del texto.
- Las observaciones de salud de los niños son datos sensibles: el art. 8 pide
  consentimiento expreso y por escrito (firma autógrafa, electrónica o mecanismo de
  autenticación). La casilla que marca la recepción por el tutor no lo cubre.
- El sistema todavía no elimina la INE, las fotografías ni los registros al vencer
  los plazos de conservación que declara el aviso.
- No se pide consentimiento al crear una reservación de evento (nombre y teléfono del
  cliente). El aviso cubre ese tratamiento, pero no queda constancia.
