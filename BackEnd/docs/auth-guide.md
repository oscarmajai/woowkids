# Woow Kids API — Guía de autenticación y permisos

Base URL local: `http://localhost:8000`
Documentación interactiva (Swagger): `http://localhost:8000/docs`

Todas las rutas de la API llevan el prefijo `/api`. Esta guía cubre la autenticación, el modelo de roles y permisos y los endpoints de administración de usuarios, sucursales y roles. El resto de los endpoints está en Swagger.

---

## Usuarios de prueba

En desarrollo, `sql/seed_local.sql` crea estos usuarios, todos con la contraseña **`12345678`** (ver [`SETUP.md`](../SETUP.md)):

| Email | Rol | Sucursal |
|-------|-----|----------|
| `sistemas@local.dev` | AdministradorSistema | — (acceso global) |
| `admin@local.dev` | Administrador | Sucursal Local |
| `cajero@local.dev` | Cajero | Sucursal Local |

En una instalación nueva solo existe el administrador de sistema inicial (`ADMIN_EMAIL` / `ADMIN_PASSWORD`). Mientras no cambie su contraseña, la API responde `403 PASSWORD_CHANGE_REQUIRED` a todo salvo `GET /api/auth/me`, `POST /api/auth/logout` y `PUT /api/usuarios/me/password`.

---

## Flujo de autenticación

### 1. Login

```
POST /api/auth/login
```

**Body:**
```json
{
  "email": "sistemas@local.dev",
  "password": "12345678",
  "rememberMe": false,
  "sucursalId": null
}
```

- `sucursalId` es opcional. Para `AdministradorSistema` se ignora. Para los roles con sucursal fija, si se envía debe coincidir con la asignada.
- Un `Administrador` con dos o más sucursales que no envía `sucursalId` recibe la lista para elegir y repite el login con la elegida:

```json
{
  "requires_branch_selection": true,
  "sucursales": [{ "id": "uuid", "nombre": "Sucursal Centro" }]
}
```

**Respuesta `200 OK`:**
```json
{
  "requires_branch_selection": false,
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4...",
  "refresh_expires_in": 604800,
  "user": {
    "id": "uuid-del-usuario",
    "full_name": "Administrador de Sistema Local",
    "email": "sistemas@local.dev",
    "role": "AdministradorSistema",
    "branch_id": null,
    "branch_name": null,
    "permissions": ["usuarios:listar", "..."],
    "tiene_pin": false,
    "debe_cambiar_password": false
  }
}
```

Además, la respuesta pone el refresh token en la cookie `refresh_token` (`HttpOnly`, `SameSite=Strict`, `Path=/api/auth`, y `Secure` si `COOKIE_SECURE=true`). Con `REFRESH_EN_BODY=false` el campo `refresh_token` del body viaja vacío y la cookie es la única vía.

**Duración de tokens:**

| | `rememberMe: false` | `rememberMe: true` |
|--|--|--|
| `token` (access) | 60 minutos | 7 días |
| `refresh_token` | 7 días | 30 días |

---

### 2. Usar el token en requests protegidos

```
Authorization: Bearer <token>
```

Un `AdministradorSistema` puede además enviar `X-Sucursal-Vista: <uuid>` para trabajar sobre una sucursal concreta; los demás roles siempre operan sobre la sucursal de su sesión.

---

### 3. Datos del usuario actual

```
GET /api/auth/me
Authorization: Bearer <token>
```

Devuelve el mismo objeto `user` del login, leído de la BD.

---

### 4. Renovar el token (refresh)

```
POST /api/auth/refresh
```

El refresh token se toma de la cookie. Si no viene, se acepta en el body por compatibilidad con clientes anteriores:

```json
{ "refreshToken": "<refresh_token_anterior>" }
```

**Respuesta `200 OK`:** mismo formato que `/login`. El refresh token se rota en cada uso: el anterior queda inválido.

---

### 5. Logout

```
POST /api/auth/logout
Authorization: Bearer <token>
```

Revoca el access token (blacklist por `jti`) y el refresh token (de la cookie o del body) y borra la cookie.

**Respuesta:** `204 No Content`

---

### 6. Ticket para WebSockets

```
POST /api/auth/ws-ticket
Authorization: Bearer <token>
```

**Respuesta:** `{ "ticket": "...", "expires_in": 30 }`. El ticket es de un solo uso y se pasa como `?ticket=` al abrir `/api/comandas/ws` o `/api/estancias/ws`. Con `WS_ACEPTA_JWT=true` los WebSockets aceptan también el JWT en `?token=`.

---

### 7. Cambiar contraseña y PIN propios

| Método | Ruta | Body |
|--------|------|------|
| `PUT` | `/api/usuarios/me/password` | `{ "actual": "...", "nueva": "..." }` (mínimo 8 caracteres) |
| `PUT` | `/api/usuarios/me/pin` | `{ "actual": "...", "pin_nuevo": "1234" }` (PIN de caja de 4 dígitos) |

---

## Roles y permisos

- Los **roles** son filas de la tabla `roles` y se administran desde el catálogo de roles. Las migraciones siembran `AdministradorSistema`, `Administrador`, `Cajero`, `Cocina` y `Personal de atención de niños`.
- Los **permisos** tienen la forma `modulo:accion` (por ejemplo `usuarios:listar`, `estancias:checkin`, `pos:acceder`) y se asignan por rol. El backend los carga en caché al arrancar y los valida en cada endpoint.
- `AdministradorSistema` tiene acceso global y no se le puede quitar ningún permiso.
- `Administrador` puede tener una o varias sucursales. Cualquier otro rol, incluidos los creados desde la UI, tiene exactamente una sucursal.

La lista completa y vigente de permisos se obtiene con `GET /api/permisos/catalogo`, y la asignación actual con `GET /api/permisos/roles`.

---

## Endpoints de administración

### Usuarios — `/api/usuarios`

| Método | Ruta | Permiso requerido | Descripción |
|--------|------|-------------------|-------------|
| `GET` | `/api/usuarios` | `usuarios:listar` | Listar usuarios |
| `POST` | `/api/usuarios` | `usuarios:crear` | Crear usuario |
| `GET` | `/api/usuarios/{id}` | `usuarios:ver` | Ver usuario |
| `PUT` | `/api/usuarios/{id}` | `usuarios:editar` | Editar usuario |
| `DELETE` | `/api/usuarios/{id}` | `usuarios:eliminar` | Eliminar usuario (borrado lógico) |

**Body para crear usuario:**
```json
{
  "email": "nuevo@ejemplo.com",
  "full_name": "Nombre",
  "apellidos": "Apellidos",
  "telefono": "3310000000",
  "password": "contraseña123",
  "role": "Cajero",
  "branch_id": "uuid-de-sucursal",
  "pin": "1234"
}
```

> `branch_id` es obligatorio para todos los roles salvo `AdministradorSistema`. `apellidos`, `telefono` y `pin` son opcionales.

### Sucursales — `/api/sucursales`

| Método | Ruta | Permiso requerido | Descripción |
|--------|------|-------------------|-------------|
| `GET` | `/api/sucursales` | `sucursales:listar` | Listar sucursales |
| `POST` | `/api/sucursales` | `sucursales:crear` | Crear sucursal |
| `GET` | `/api/sucursales/{id}` | `sucursales:ver` | Ver sucursal |
| `PUT` | `/api/sucursales/{id}` | `sucursales:editar` | Editar sucursal |
| `PATCH` | `/api/sucursales/{id}/deactivate` | `sucursales:eliminar` | Desactivar sucursal |
| `PATCH` | `/api/sucursales/{id}/reactivate` | `sucursales:editar` | Reactivar sucursal |
| `GET` | `/api/sucursales/{id}/indicadores` | `sucursales:ver` | Indicadores de la sucursal |

**Body para crear o editar sucursal** (solo `nombre` es obligatorio):
```json
{
  "nombre": "Sucursal Centro",
  "direccion": "Av. Principal 123",
  "ciudad": "Guadalajara",
  "estado": "Jalisco",
  "codigo_postal": "44100",
  "zona_horaria": "America/Mexico_City",
  "hora_apertura": "09:00",
  "hora_cierre": "23:00",
  "telefono": "3310000000",
  "correo": "centro@ejemplo.com",
  "clave": "CENTRO"
}
```

> `Administrador` solo ve y edita sus sucursales. `AdministradorSistema` tiene acceso a todas.

### Roles y permisos — `/api/permisos`

| Método | Ruta | Permiso requerido | Descripción |
|--------|------|-------------------|-------------|
| `GET` | `/api/permisos/roles` | `permisos:ver` | Listar roles con sus permisos |
| `GET` | `/api/permisos/roles/{id}` | `permisos:ver` | Ver un rol |
| `POST` | `/api/permisos/roles` | `permisos:editar` | Crear rol (`nombre`, `descripcion`, `permiso_ids`) |
| `PATCH` | `/api/permisos/roles/{id}` | `permisos:editar` | Renombrar, describir o activar/desactivar un rol |
| `PUT` | `/api/permisos/roles/{id}` | `permisos:editar` | Reemplazar los permisos de un rol (`permiso_ids`) |
| `GET` | `/api/permisos/catalogo` | `permisos:ver` | Catálogo completo de permisos |
| `POST` | `/api/permisos/cache/reload` | `permisos:editar` | Forzar recarga del caché de permisos |

**Body para actualizar permisos de un rol (`PUT /api/permisos/roles/{id}`):**
```json
{ "permiso_ids": [1, 2, 3, 4, 5] }
```

> Los IDs se obtienen de `GET /api/permisos/catalogo`.

---

## Ejemplos rápidos con curl

```bash
# Login (guarda la cookie del refresh token en cookies.txt)
curl -c cookies.txt -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "sistemas@local.dev", "password": "12345678"}'

# Listar usuarios
curl http://localhost:8000/api/usuarios -H "Authorization: Bearer <token>"

# Renovar el token con la cookie
curl -b cookies.txt -c cookies.txt -X POST http://localhost:8000/api/auth/refresh
```

---

## Errores comunes

Los errores llegan como `{ "detail": { "code": "...", "message": "..." } }`.

| Código HTTP | `code` | Causa |
|-------------|--------|-------|
| `401` | `INVALID_CREDENTIALS` | Email o contraseña incorrectos |
| `401` | `NO_BRANCH_ASSIGNED` | El usuario no tiene ninguna sucursal activa asignada |
| `401` | `INVALID_TOKEN` | Access token expirado, inválido o revocado |
| `401` | `TOKEN_INVALID` | Refresh token inválido, expirado o ya usado |
| `401` | `ACCOUNT_DISABLED` | La cuenta fue desactivada |
| `403` | `FORBIDDEN` | El rol no tiene el permiso requerido o el recurso es de otra sucursal |
| `403` | `PASSWORD_CHANGE_REQUIRED` | El usuario debe cambiar su contraseña antes de seguir |
| `404` | `USER_NOT_FOUND` / `BRANCH_NOT_FOUND` | El recurso no existe |
| `409` | `EMAIL_ALREADY_EXISTS` | Ya hay un usuario con ese email |
| `422` | `BRANCH_REQUIRED` | Se intentó crear un usuario sin sucursal para un rol que la exige |
| `503` | `SERVICE_UNAVAILABLE` | La BD no respondió a tiempo al verificar la sesión |
