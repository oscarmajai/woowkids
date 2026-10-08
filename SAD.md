# SAD — Software Architecture Document
## Woow Kids (proyecto Mercury)

**Versión del documento:** 2.0  
**Fecha:** 2026-10-05  
**Alcance:** monorepo completo (`FrontEnd/` y `BackEnd/`), rama `develop`

---

## Tabla de contenidos

1. [Visión general del sistema](#1-visión-general-del-sistema)
2. [Repositorio y estructura de proyecto](#2-repositorio-y-estructura-de-proyecto)
3. [Arquitectura del BackEnd](#3-arquitectura-del-backend)
4. [Arquitectura del FrontEnd](#4-arquitectura-del-frontend)
5. [Base de datos](#5-base-de-datos)
6. [Autenticación y autorización](#6-autenticación-y-autorización)
7. [Comunicación FrontEnd ↔ BackEnd](#7-comunicación-frontend--backend)
8. [Flujo Git y releases](#8-flujo-git-y-releases)
9. [Calidad de código](#9-calidad-de-código)
10. [Catálogo de módulos](#10-catálogo-de-módulos)
11. [Reglas que NO se deben romper](#11-reglas-que-no-se-deben-romper)
12. [Deuda técnica activa](#12-deuda-técnica-activa)

---

## 1. Visión general del sistema

Woow Kids es un sistema "todo en uno" para franquicias de entretenimiento infantil (FEC). Gestiona:

- **Estancias**: registro de niños y tutores, entrada y salida con pulseras RFID, cobro por tiempo.
- **Caja (POS) y cocina**: comandas, cobros, turnos y cierres de caja.
- **Eventos y reservaciones**: calendario, paquetes, extras y pagos.
- **Inventario**: insumos, proveedores, compras, recetas de productos y movimientos (kardex, costeo FIFO).
- **Lealtad**: puntos por celular y sucursal, con canje.
- **Administración multisucursal**: sucursales, usuarios, roles y permisos, horarios, aviso de privacidad y respaldos.
- **Portal de padres**: consulta de la estancia en curso con un código de acceso.

Todo el código vive en un solo repositorio (monorepo). El FrontEnd es una SPA que habla con el BackEnd por HTTP REST y WebSockets bajo el prefijo `/api`:

```
Navegador
   │
   ▼
nginx ──── archivos estáticos de la SPA (Vue 3 + Quasar)
   │
   └── /api ──▶ BackEnd (FastAPI + asyncpg) ──▶ PostgreSQL
                         │
                         └──▶ MinIO (fotos, documentos)
```

Se despliega de dos formas (ver [`README.md`](README.md)):

- **Contenedores separados** (`docker-compose.yml`): `db`, `minio`, `backend`, `respaldos` y `frontend`.
- **Contenedor único** (`Dockerfile.allinone` + `docker/allinone/`): nginx, API, PostgreSQL y MinIO bajo `supervisord`, con los datos en el volumen `/data`.

---

## 2. Repositorio y estructura de proyecto

```
Mercury/
├── README.md                  ← cómo levantar el sistema
├── CONTRIBUTING.md            ← Git Flow, commits y calidad
├── SAD.md                     ← este documento
├── docker-compose.yml         ← stack de contenedores separados
├── Dockerfile.allinone        ← imagen todo en uno
├── docker/allinone/           ← nginx, supervisord, TLS y arranque de la imagen todo en uno
├── .github/                   ← CI (ci.yml), release (release.yml) y cálculo de versión
├── BackEnd/                   ← API REST y WebSockets (Python / FastAPI)
└── FrontEnd/                  ← SPA (Vue 3 / Quasar / TypeScript)
```

### BackEnd

```
BackEnd/
├── app/
│   ├── main.py                  # Entry point: crea la app, monta routers, lifespan
│   ├── core/
│   │   ├── config.py            # Settings con pydantic-settings (lee .env)
│   │   ├── database.py          # Pool asyncpg + dependencia get_db
│   │   ├── security.py          # JWT, bcrypt, refresh tokens, tickets de WebSocket
│   │   ├── object_storage.py    # Cliente S3 de MinIO
│   │   ├── roles.py             # Roles estructurales (AdministradorSistema, Administrador)
│   │   ├── scope.py             # Regla de aislamiento por sucursal
│   │   └── ws_manager.py        # Conexiones WebSocket por sucursal
│   ├── api/
│   │   ├── deps.py              # get_current_user, require_role, require_permission
│   │   └── routers/             # Un archivo por recurso
│   ├── schemas/                 # Modelos Pydantic v2 (request / response, NO son tablas)
│   ├── services/                # Lógica de negocio (incluye los schedulers del lifespan)
│   ├── repositories/            # Acceso a BD (SQL crudo con asyncpg)
│   ├── models/                  # Entidades de dominio como dataclasses (sin ORM)
│   ├── exceptions/              # Excepciones HTTP y manejadores globales
│   └── utils/                   # Utilidades (exportación CSV)
├── sql/
│   ├── migrations/              # Archivos .sql versionados (001_, 002_, …)
│   ├── schema_maestro.sql       # BD completa generada desde las migraciones
│   └── seed_local.sql           # Datos de prueba para desarrollo
├── tests/
│   ├── unit/                    # Pruebas sin BD
│   └── db/                      # Pruebas contra un PostgreSQL real (TEST_DATABASE_URL)
├── docker/                      # entrypoint.sh (migraciones, SECRET_KEY, admin inicial) y respaldos.sh
├── scripts/                     # Schema maestro, BD local, prueba de migraciones, respaldos
├── docs/                        # Guías (autenticación, aviso de privacidad)
├── Dockerfile
├── docker-compose.dev.yml       # PostgreSQL + MinIO para desarrollo
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml               # Ruff + mypy + pytest
└── .env.example
```

### FrontEnd

```
FrontEnd/
├── src/
│   ├── main.ts                  # Entry point Vue
│   ├── App.vue
│   ├── boot/
│   │   └── setupPlugins.ts      # Inicializa Quasar, Pinia, router, guards, inactividad
│   ├── api/                     # Llamadas HTTP (solo arma y dispara la request)
│   ├── services/                # Lógica de negocio del cliente (orquesta api/)
│   ├── stores/                  # Estado global con Pinia
│   ├── composables/             # Lógica reutilizable (use*), incluido el menú lateral
│   ├── router/
│   │   ├── index.ts             # Definición de rutas
│   │   └── guards.ts            # Guardias de autenticación, permisos y turno de caja
│   ├── layouts/                 # AuthLayout, AppShell, PublicLayout, PadresLayout
│   ├── pages/                   # Vistas ruteadas
│   ├── components/              # Componentes por módulo, ui/ (kit base) y layout/ (sidebar, topbar)
│   ├── types/                   # Interfaces y tipos TypeScript compartidos
│   ├── utils/                   # Funciones puras de utilidad
│   └── css/app.scss             # Paleta, tipografía y variables CSS globales
├── .husky/                      # Hooks de Git del monorepo (pre-commit, commit-msg)
├── Dockerfile                   # Build con Node + nginx
├── nginx.conf                   # Sirve la SPA y hace proxy de /api al backend
├── package.json
├── quasar.config.ts
├── vite.config.ts
├── vitest.config.ts
└── tsconfig.json
```

Las pruebas del FrontEnd viven junto al código, en carpetas `__tests__/`.

---

## 3. Arquitectura del BackEnd

### 3.1 Stack

| Tecnología | Versión | Uso |
|---|---|---|
| Python | 3.12 (imagen y CI; mínimo 3.11) | Lenguaje |
| FastAPI | 0.115.x | Framework HTTP y WebSockets |
| Uvicorn | 0.34.x | Servidor ASGI |
| asyncpg | 0.31.x | Driver PostgreSQL (async) |
| Pydantic v2 | 2.10.x | Validación y schemas |
| pydantic-settings | 2.7.x | Variables de entorno |
| python-jose | 3.3.x | JWT |
| bcrypt | 5.0.x | Hash de contraseñas y PIN |
| boto3 | 1.35.x | Cliente S3 para MinIO |
| ReportLab | 5.0.x | Comprobantes en PDF |
| PostgreSQL | 16 | Base de datos |
| Ruff | 0.8.x | Lint y formato |
| mypy | 1.13.x | Type checking |
| pytest | 8.3.x | Pruebas |

### 3.2 Flujo de una request

```
HTTP Request
    │
    ▼
Router (app/api/routers/*.py)
    │  Valida schema Pydantic, extrae usuario autenticado via Depends
    ▼
Service (app/services/*.py)
    │  Lógica de negocio, orquesta uno o varios repositorios
    ▼
Repository (app/repositories/*.py)
    │  ÚNICA capa que habla con la BD — SQL crudo con asyncpg
    ▼
PostgreSQL
```

**Regla de capas (estricta):**
- Un **router** llama solo a un **service**. Nunca accede a un repository directamente.
- Un **service** llama a uno o varios **repositories**. Nunca arma una query SQL.
- Un **repository** es el único lugar donde se escribe SQL. Nunca contiene lógica de negocio.
- Los **schemas** son contratos de entrada/salida de la API. No representan tablas de BD.

### 3.3 Acceso a base de datos

El acceso a BD se hace **exclusivamente con asyncpg y SQL parametrizado**. Ejemplo del patrón correcto:

```python
# ✅ CORRECTO — asyncpg con query parametrizada
async def get_user_by_email(conn: asyncpg.Connection, email: str) -> UsuarioRecord | None:
    row = await conn.fetchrow(
        "SELECT id, email, password_hash FROM public.usuarios WHERE email = $1 AND activo = TRUE",
        email,
    )
    return _row_to_record(row) if row else None
```

```python
# ❌ INCORRECTO — nunca interpolar valores con f-strings
row = await conn.fetchrow(f"SELECT * FROM usuarios WHERE email = '{email}'")  # SQL injection

# ❌ INCORRECTO — nunca usar un ORM
from sqlalchemy.orm import Session  # PROHIBIDO
db.query(Usuario).filter(...)       # PROHIBIDO
```

La dependencia de base de datos se inyecta via FastAPI `Depends`:

```python
from app.core.database import get_db

@router.get("/usuarios")
async def listar(conn: asyncpg.Connection = Depends(get_db)) -> list[UserOut]:
    return await user_service.listar_todos(conn)
```

El pool tiene tamaño y tiempos límite configurables (`DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`, `DB_POOL_ACQUIRE_TIMEOUT`, `DB_COMMAND_TIMEOUT`). Si una petición no consigue conexión a tiempo, la API responde 503 en lugar de quedarse colgada.

### 3.4 Configuración

Toda la configuración viene de variables de entorno (o del archivo `.env`) mediante `pydantic-settings`. **Nunca hardcodear** credenciales, URLs de BD, secret keys ni CORS origins en el código.

```python
# app/core/config.py — extracto
class Settings(BaseSettings):
    secret_key: str
    algorithm: str = "HS256"
    database_url: str
    cors_origins: list[str] = ["http://localhost:5173"]
    minio_endpoint: str = "minio:9000"
    minio_access_key: str
    minio_secret_key: str
```

Variables principales (ver `BackEnd/.env.example` y, para los contenedores, `.env.example` de la raíz):

| Variable | Uso |
|---|---|
| `SECRET_KEY` | Clave de firma JWT. En contenedor, si viene vacía, `docker/entrypoint.sh` genera una y la guarda en la BD. La API rechaza la clave de fábrica. |
| `DATABASE_URL` | Cadena de conexión PostgreSQL. |
| `CORS_ORIGINS` | Lista JSON de orígenes permitidos. |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `MINIO_SECURE` | Almacenamiento de archivos. |
| `COOKIE_SECURE` | Marca la cookie del refresh token como `Secure` (requiere HTTPS). |
| `REFRESH_EN_BODY`, `WS_ACEPTA_JWT`, `EXIGIR_PIN_TOKEN` | Compatibilidad con clientes anteriores (ver [§12](#12-deuda-técnica-activa)). |

### 3.5 Entry point y lifespan

El entry point es **`app/main.py`**. No existe `main.py` en la raíz. El lifespan inicializa el pool de conexiones, carga el caché de permisos, asegura que exista el bucket de MinIO y arranca dos tareas periódicas:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await create_pool()                                   # pool asyncpg
    async with get_pool().acquire() as conn:
        await load_cache(conn)                            # permisos en memoria
    await ensure_bucket()                                 # bucket de MinIO
    scheduler_task = asyncio.create_task(loop_comandas_eventos())
    vencidas_task = asyncio.create_task(loop_reservaciones_vencidas())
    yield
    scheduler_task.cancel()
    vencidas_task.cancel()
    await close_pool()
```

Para correr en desarrollo: `uvicorn app.main:app --reload` (ver [`BackEnd/SETUP.md`](BackEnd/SETUP.md)). Sin MinIO disponible el arranque no termina.

### 3.6 Tiempo real (WebSockets)

Comandas (`/api/comandas/ws`) y estancias (`/api/estancias/ws`) notifican cambios por WebSocket. `app/core/ws_manager.py` agrupa las conexiones por sucursal. El cliente se autentica con un ticket de un solo uso que pide a `POST /api/auth/ws-ticket` (vigencia de 30 s), para no poner el JWT en la URL.

### 3.7 Archivos

Fotos de niños, identificaciones de tutores, imágenes de productos y demás documentos se guardan en MinIO (API S3) y se sirven a través de la API (`/api/uploads`). Las imágenes de productos son públicas (se muestran en `<img>`); el resto exige sesión y se autoriza por recurso (permiso y sucursal).

### 3.8 Arranque en contenedor y respaldos

`BackEnd/docker/entrypoint.sh` prepara la BD antes de levantar la API:

1. Si la BD está vacía, la crea con `sql/schema_maestro.sql` (y `sql/seed_local.sql` si `SEED_DEMO=true`).
2. Aplica las migraciones pendientes y las registra en `public.schema_migraciones`. Antes de migrar una BD con datos guarda un respaldo.
3. Resuelve `SECRET_KEY` y crea el administrador de sistema inicial, que debe cambiar su contraseña al entrar.

Los respaldos programados de BD y archivos los hace `scripts/respaldos.py` (servicio `respaldos` en el compose, proceso propio en la imagen todo en uno).

---

## 4. Arquitectura del FrontEnd

### 4.1 Stack

| Tecnología | Versión | Uso |
|---|---|---|
| Vue 3 | 3.5.x | Framework UI |
| TypeScript | 6.x | Lenguaje |
| Quasar | 2.x | Componentes UI |
| Pinia | 3.x | Estado global |
| Vue Router | 4.x | Enrutamiento (history mode) |
| Axios | 1.x | HTTP client |
| Vite | 8.x | Build tool y dev server |
| ESLint + Prettier | — | Lint y formato |
| vue-tsc | 3.x | Type checking |
| Vitest | 4.x | Tests unitarios y de componentes |

La tipografía (Plus Jakarta Sans) y los íconos van empaquetados en el build: la aplicación no necesita internet en operación.

### 4.2 Flujo de datos

```
Page / Component
    │  Solo llama a services/ o stores/. Nunca a api/ directamente.
    ▼
Service (src/services/*.ts)
    │  Orquesta llamadas HTTP. Contiene lógica de presentación compleja.
    ▼
API Module (src/api/*.ts)
    │  Solo arma la request y la dispara con apiClient. Sin lógica.
    ▼
apiClient (src/api/axiosClient.ts)
    │  Instancia Axios con interceptores de auth, refresh automático y errores.
    ▼
BackEnd REST API
```

El estado persistente va en **stores** (Pinia). Los componentes leen del store directamente.

### 4.3 Composición de componentes

**Siempre** usar `<script setup lang="ts">`. La Options API está prohibida.

```vue
<!-- ✅ CORRECTO -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'   // ← composables, no $route/$router
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
</script>
```

```vue
<!-- ❌ INCORRECTO — Options API -->
<script lang="ts">
export default {
  data() { return {} },
  methods: {
    ir() { this.$router.push('/') }   // ← this.$router / this.$route PROHIBIDO
  }
}
</script>
```

Los componentes base reutilizables (`PageHeader`, `DataTableCard`, `BaseDialog`, `KpiCard`, `StatusBadge`, `StateBlock`, `TablePager`) están en `src/components/ui/`.

### 4.4 Layouts y enrutamiento

| Layout | Rutas | Quién |
|---|---|---|
| `AuthLayout` | `/login`, `/cambiar-password` | Público / usuario que debe cambiar su contraseña |
| `AppShell` | `/home`, `/pos/*`, `/estancias/*`, `/eventos/*`, `/usuarios`, `/sucursales`, `/reportes/*`, catálogos… | Personal autenticado (sidebar + topbar) |
| `PublicLayout` | `/aviso-de-privacidad` | Público |
| `PadresLayout` | `/padres/*` | Tutores con código de acceso |

El menú lateral se arma en `src/composables/useAppNavigation.ts` y se filtra por permisos. El guard en `src/router/guards.ts` corre en cada navegación:

```typescript
// Flujo del guard (resumen)
// 1. Si requiresAuth y no autenticado → intenta refresh → si no, redirige a /login
// 2. Si publicOnly y ya autenticado → redirige a /home
// 3. Si el usuario debe cambiar su contraseña → redirige a /cambiar-password
// 4. Si meta.permissions o meta.roles definidos → verifica que el usuario tenga alguno
// 5. Si meta.requiresTurno → exige un turno de caja abierto
```

Las rutas protegidas se declaran con `meta.requiresAuth` y, preferentemente, con permisos (los roles son datos editables, los permisos no):

```typescript
{
  path: 'cocina',
  name: 'pos-cocina',
  component: () => import('@/components/comandas/VisorCocina.vue'),
  meta: { permissions: ['restaurante:gestionar_cocina'], title: 'Visor Cocina' },
}
```

### 4.5 Manejo de errores HTTP

El `apiClient` tiene interceptores que:
1. Adjuntan el Bearer token (que vive solo en memoria) a cada request y, para AdministradorSistema, el header `X-Sucursal-Vista` con la sucursal elegida en el selector.
2. En un 401: intentan refresh automático una sola vez (con la cookie HttpOnly del refresh token).
3. Si el refresh falla: disparan el evento `auth:unauthorized` → el boot de la app hace logout y redirige a login.
4. Si hay múltiples requests en vuelo durante el refresh: comparten el mismo refresh y reintentan con el nuevo token.
5. Normalizan cualquier error a `ApiError { statusCode, code, message, details? }`.

**No re-implementes este flujo** en ningún otro módulo. Todos los módulos usan `apiClient` de `@/api/axiosClient`.

---

## 5. Base de datos

### 5.1 Motor y acceso

- **Motor:** PostgreSQL 16
- **Driver:** asyncpg (directo, sin ORM)
- **Queries:** SQL parametrizado (`$1`, `$2`, ...)
- **Pool:** inicializado en el lifespan de la app, accesible via `get_pool()`

### 5.2 Esquema base

```
public.roles
  id | nombre | descripcion             ← los roles son filas, no un ENUM

public.usuarios
  id UUID PK | email | password_hash | nombre_completo | rol FK → roles | pin_hash | debe_cambiar_password | activo | auditoría

public.sucursales
  id UUID PK | nombre | direccion | telefono | correo | clave | activo | auditoría

public.usuarios_sucursal
  id UUID PK | usuario_id FK → usuarios | sucursal_id FK → sucursales | activo | auditoría

public.permisos / public.rol_permisos
  catálogo de permisos (codigo = "modulo:accion") y su asignación por rol
```

Los IDs de las entidades son `UUID` generados con `gen_random_uuid()`. Las tablas de negocio llevan campos de auditoría (`creado`, `creado_por`, `modificado`, `modificado_por`) y borrado lógico con `activo`.

### 5.3 Roles

Los roles viven en la tabla `public.roles` y se administran desde el catálogo de roles de la aplicación. Las migraciones siembran:

- **AdministradorSistema**: acceso global, sin entrada en `usuarios_sucursal`. No se le puede quitar ningún permiso.
- **Administrador**: una o más sucursales asignadas en `usuarios_sucursal`.
- **Cajero**, **Cocina**, **Personal de atención de niños** y cualquier rol creado desde la UI: exactamente una sucursal.

Solo `AdministradorSistema` y `Administrador` tienen comportamiento especial en el código (`app/core/roles.py`). Lo demás se decide por permisos.

### 5.4 Migraciones

Las migraciones son archivos SQL en `BackEnd/sql/migrations/` con prefijo numérico incremental:

```
001_initial_schema.sql         — usuarios, sucursales, usuarios_sucursal
002_token_blacklist.sql        — blacklist de access tokens
003_refresh_tokens.sql         — tabla de refresh tokens
004_roles_permisos.sql         — tabla de roles y permisos granulares
…
```

- `sql/schema_maestro.sql` se **genera** aplicando todas las migraciones (`scripts/generar_schema_maestro.sh`) y sirve para crear una BD nueva. El CI verifica que esté al día.
- Al arrancar, el contenedor aplica solo las migraciones que falten y las registra en `public.schema_migraciones` (ver [§3.8](#38-arranque-en-contenedor-y-respaldos)).
- Cada migración corre en una transacción junto con su registro: no lleva `BEGIN`/`COMMIT` propios.

**Regla:** nunca modificar una migración ya publicada. Siempre crear un archivo nuevo con el siguiente número y regenerar el maestro.

---

## 6. Autenticación y autorización

Detalle de endpoints y ejemplos en [`BackEnd/docs/auth-guide.md`](BackEnd/docs/auth-guide.md).

### 6.1 Flujo de login

```
FrontEnd                              BackEnd
   │                                     │
   │  POST /api/auth/login               │
   │  { email, password, rememberMe,     │
   │    sucursalId? }                    │
   │ ──────────────────────────────────▶ │
   │                                     │ Verifica credenciales
   │                                     │ Genera access token (JWT) + refresh token
   │ ◀────────────────────────────────── │
   │  { token, expires_in, user, … }     │
   │  Set-Cookie: refresh_token          │
   │  (HttpOnly; SameSite=Strict;        │
   │   Path=/api/auth)                   │
   │                                     │
   │  Access token en memoria            │
   │  Bearer en cada request             │
```

Un Administrador con dos o más sucursales recibe primero `{ requires_branch_selection: true, sucursales: [...] }` y repite el login con `sucursalId`.

### 6.2 JWT (access token)

**Payload del token:**
```json
{
  "sub": "uuid-del-usuario",
  "email": "usuario@ejemplo.com",
  "role": "Cajero",
  "branch_id": "uuid-de-sucursal",
  "permissions": ["pos:acceder", "..."],
  "jti": "uuid-único-del-token",
  "iat": 1234567890,
  "exp": 1234571490
}
```

- El `jti` se verifica contra la blacklist en cada request protegida.
- El backend valida cada permiso contra el caché de permisos por rol (no contra la lista del token), así que un cambio de permisos aplica de inmediato. El frontend recibe la lista en `user.permissions` y la usa para mostrar u ocultar UI.

### 6.3 Refresh token

- Es un valor aleatorio opaco que se almacena hasheado (SHA-256) en la tabla `refresh_tokens`.
- Viaja en la cookie HttpOnly `refresh_token`. Ante un 401, el interceptor de Axios llama a `POST /api/auth/refresh`.
- Cada refresh invalida el token anterior y emite uno nuevo (rotación).

### 6.4 Protección de endpoints en el BackEnd

```python
from app.api.deps import require_role, require_permission, get_current_user
from app.core.roles import ROL_SISTEMA

# Cualquier usuario autenticado
@router.get("/me")
async def me(user: TokenData = Depends(get_current_user)):
    ...

# Solo un rol específico
@router.get("/sistema/respaldos")
async def estado_respaldos(user: TokenData = Depends(require_role(ROL_SISTEMA))):
    ...

# Por código de permiso (preferido)
@router.patch("/sucursales/{id}/deactivate")
async def desactivar(user: TokenData = Depends(require_permission("sucursales:eliminar"))):
    ...
```

Además del permiso, cada consulta se limita a la sucursal de la sesión (`app/core/scope.py`): un rol con sucursal fija que pide datos de otra recibe 403, y un recurso de otra sucursal pedido por id responde 404.

### 6.5 Protección de rutas en el FrontEnd

```typescript
// En router/index.ts:
meta: { requiresAuth: true, permissions: ['usuarios:listar'] }

// El guard en router/guards.ts lo verifica automáticamente.
// No añadir lógica de auth en los componentes.
```

### 6.6 Inactividad

La sesión se cierra automáticamente tras 15 minutos de inactividad (configurado en `setupPlugins.ts`). El timer se reinicia con cualquier interacción del usuario.

---

## 7. Comunicación FrontEnd ↔ BackEnd

### 7.1 URL base

Configurada en el `.env` del FrontEnd (o como argumento de build de la imagen):
```
VITE_API_BASE_URL=http://localhost:8000/api
```

En las imágenes Docker vale `/api`: nginx sirve la SPA y redirige `/api` (incluidos los WebSockets) al backend, así que navegador y API comparten origen.

### 7.2 Patrón de módulo API

Cada recurso tiene su propio archivo en `src/api/`:

```typescript
// src/api/<recurso>Api.ts — SOLO arma la request, sin lógica (simplificado)
import { apiClient } from './axiosClient'
import type { Paquetes } from '@/types/paquetes'

export const paquetesApi = {
  listar: (sucursal_id?: string) =>
    apiClient
      .get<Paquetes[]>('/paquetes', { params: sucursal_id ? { sucursal_id } : undefined })
      .then((r) => r.data),
  obtener: (id: string) => apiClient.get<Paquetes>(`/paquetes/${id}`).then((r) => r.data),
}
```

### 7.3 Proxy de desarrollo

En `vite.config.ts` hay un proxy de `/api` (con WebSockets) hacia `http://127.0.0.1:8000`, o hacia `VITE_PROXY_TARGET` si está definida.

### 7.4 Formato de errores

El backend responde los errores de negocio como `{ "detail": { "code": "...", "message": "..." } }`; los 422 de validación de FastAPI traen `detail` como lista. El `apiClient` normaliza ambos formatos (ver [§4.5](#45-manejo-de-errores-http)).

---

## 8. Flujo Git y releases

Las reglas completas están en [`CONTRIBUTING.md`](CONTRIBUTING.md).

### 8.1 Estructura de ramas (Git Flow)

```
main                         ← producción: cada llegada publica un release
  ├── hotfix/<descripcion>   ← urgencias, salen de main
  └── develop                ← integración
        ├── feature/<issue>-<descripcion>
        ├── fix/<issue>-<descripcion>
        └── release/<version>
```

### 8.2 Ciclo de vida de un cambio

```
1. Crear la rama desde develop actualizado:
   git checkout develop && git pull && git checkout -b feature/42-nueva-funcionalidad

2. Desarrollar con commits atómicos (Conventional Commits).

3. Abrir un Pull Request hacia develop. El CI verifica la parte que cambió.

4. Revisar y mergear el PR en develop.

5. Para publicar: llevar develop a main por Pull Request (con una rama release/<version>
   cuando haga falta preparar la versión). El workflow de release corre el CI completo,
   calcula la versión, crea el tag y publica la imagen.
```

Un cambio que toca FrontEnd y BackEnd a la vez va en **una sola rama y un solo PR**.

### 8.3 Versionado

La versión la calcula `release.yml` (con `.github/scripts/siguiente_version.sh`) a partir de los commits desde el último tag `vX.Y.Z`:

| Commits desde el último tag | Sube |
|---|---|
| `tipo!:` o `BREAKING CHANGE` | mayor |
| `feat:` | menor |
| cualquier otro | parche |

Cada release publica `ghcr.io/<owner>/woowkids:vX.Y.Z` y `:latest` y crea el GitHub Release.

### 8.4 Conventional Commits

Formato obligatorio, **sin scope**: `<tipo>: <descripción en minúscula, imperativo, sin punto final>`. Lo valida el hook `commit-msg` (commitlint).

| Tipo | Cuándo usarlo |
|---|---|
| `feat` | Nueva funcionalidad |
| `fix` | Corrección de bug |
| `chore` | Tareas de mantenimiento (deps, config) |
| `refactor` | Refactorización sin cambio de comportamiento |
| `docs` | Documentación |
| `style` | Formato, espacios (sin cambio lógico) |
| `test` | Tests |
| `perf` | Mejora de rendimiento |
| `build` | Sistema de build, dependencias, imágenes |
| `ci` | Workflows de CI/CD |
| `revert` | Reversión de commit |

Los issues se referencian en el cuerpo con `Refs #N` o `Closes #N`.

```
✅  feat: agregar endpoint de reactivacion de sucursales
✅  fix: corregir validacion de token expirado en guard
❌  feat(auth): agregar login                              ← con scope
❌  Feat: Agregar endpoint de reactivación de Sucursales.   ← mayúscula, punto final
❌  update stuff                                            ← sin tipo
```

---

## 9. Calidad de código

Los mismos comandos que corre el CI. Deben pasar antes de cada commit.

### BackEnd (en `BackEnd/`)

```bash
ruff check .            # lint
ruff format --check .   # formato (ruff format . para aplicarlo)
mypy app                # type check
pytest tests/unit       # tests unitarios
```

El CI corre además `pytest tests/db` contra un PostgreSQL real, regenera el schema maestro para verificar que esté al día y prueba el control de migraciones del arranque con la imagen construida. Si cambias migraciones, corre `scripts/generar_schema_maestro.sh` y commitea el maestro.

### FrontEnd (en `FrontEnd/`)

```bash
npx eslint src            # ESLint + Prettier
npm run type-check        # vue-tsc
npx vitest run --dir src  # Vitest
```

### Hooks de Git

Se instalan con `npm install` dentro de `FrontEnd/` y aplican a todo el monorepo:

- **pre-commit:** verifica solo la parte con archivos en stage. FrontEnd: lint-staged (ESLint + Prettier) y vue-tsc. BackEnd: ruff y mypy (si existe `BackEnd/.venv`).
- **commit-msg:** commitlint con Conventional Commits sin scope.

Si un hook falla, **corrige el error, no lo evadas**.

### Reglas de tipo

- **BackEnd:** type hints obligatorios en toda función pública (mypy en modo estricto). No usar `Any` salvo con `# type: ignore` documentado.
- **FrontEnd:** TypeScript estricto. Evitar `any`. Tipar todo lo que cruce una frontera (respuestas API, props, eventos).

---

## 10. Catálogo de módulos

### BackEnd

Cada módulo sigue router → service → repository. Los routers están en `app/api/routers/`.

| Módulo | Routers |
|---|---|
| Autenticación | `auth.py` (login, refresh, logout, me, ws-ticket) |
| Usuarios, roles y permisos | `users.py`, `permissions.py` |
| Sucursales y horarios | `branches.py`, `horarios.py` |
| Estancias y pulseras | `estancias.py`, `pulseras.py`, `documentos.py` |
| Portal de padres | `padres.py` |
| Caja (POS) y cocina | `comandas.py`, `pagos.py`, `metodos_pago.py`, `turnos_caja.py`, `cajas_admin.py` |
| Productos | `productos.py`, `producto_insumos.py` (recetas) |
| Inventario | `insumos.py`, `presentaciones_insumo.py`, `unidades_medida.py`, `proveedores.py`, `compras.py`, `movimientos_inventario.py` |
| Eventos y reservaciones | `reservaciones.py`, `reservacion_extras.py`, `reservacion_productos.py`, `pagos_reservacion.py`, `paquetes.py`, `paquete_tipos_evento.py`, `tipos_evento.py`, `extras.py` |
| Lealtad | `lealtad.py` |
| Privacidad | `privacidad.py` (aviso de privacidad, ver [`BackEnd/docs/aviso-privacidad.md`](BackEnd/docs/aviso-privacidad.md)) |
| Sistema | `sistema.py` (estado de los respaldos) |

La documentación interactiva de todos los endpoints está en `/docs` (Swagger) del backend.

### FrontEnd

| Módulo | Rutas | Páginas principales |
|---|---|---|
| Autenticación | `/login`, `/cambiar-password` | `pages/auth/` |
| Inicio | `/home` | `pages/home/HomePage.vue` |
| Caja (POS) y cocina | `/pos/caja`, `/pos/cocina`, `/pos/cierre`, `/pos/historial`, `/pos/historial-arqueos` | `components/DashboardComponent.vue`, `components/comandas/VisorCocina.vue`, `CierreCajaPage.vue`, `components/historial/HistorialView.vue`, `HistorialArqueosPage.vue` |
| Estancias | `/estancias/*` | `RegistrationPage.vue`, `AccessControlPage.vue`, `CheckoutPage.vue`, `PulserasPage.vue`, `RegistroPulserasPage.vue` |
| Eventos y reservaciones | `/eventos/*` | `DashboardPage.vue` (resumen), `ReservacionesPage.vue`, `NuevaReservacionPage.vue`, `CalendarioPage.vue`, `CierreEventoPage.vue`, `PagosPage.vue` |
| Catálogos | `/productos`, `/extras`, `/paquetes`, `/tipos-evento`, `/metodos-pago` | páginas homónimas en `pages/` |
| Inventario | `/insumos`, `/insumos/:id/kardex`, `/proveedores`, `/compras` | `InsumosPage.vue`, `KardexInsumoPage.vue`, `ProveedoresPage.vue`, `ComprasPage.vue` |
| Reportes | `/reportes/*` | `sysadmin/SysAdminDashboardPage.vue`, `ReporteInventarioPage.vue`, `ReporteCogsPage.vue` |
| Administración | `/usuarios`, `/roles`, `/sucursales`, `/admin/horarios`, `/admin/cajas`, `/admin/aviso-privacidad` | `sysadmin/UsersPage.vue`, `RolesPage.vue`, `locations/SucursalesPage.vue`, `pages/admin/` |
| Lealtad | `/lealtad/configuracion`, `/lealtad/kardex`, `/lealtad/reporte` | `LealtadConfiguracionPage.vue`, `KardexLealtadPage.vue`, `ReporteLealtadPage.vue` |
| Portal de padres | `/padres/*` | `pages/padres/` |
| Aviso de privacidad (público) | `/aviso-de-privacidad` | `AvisoPrivacidadPage.vue` |

---

## 11. Reglas que NO se deben romper

Cada regla tiene un ejemplo del problema y la solución correcta. El código hace referencia a estas reglas por su número (p. ej. "Regla 11.1 SAD"), así que la numeración se mantiene.

---

### 11.1 BackEnd: NO usar ORM — solo asyncpg con SQL crudo

**Problema:** usar SQLAlchemy (modelos con `Base`, `Session`, `db.query(...)`) contradice la arquitectura del proyecto y causa conflictos con el pool asyncpg.

```python
# ❌ PROHIBIDO — SQLAlchemy ORM
from sqlalchemy.orm import Session
from sqlalchemy import Column, String
from app.core.database import Base   # Base no existe en este proyecto

class Comanda(Base):
    __tablename__ = "comandas"
    id = Column(String, primary_key=True)

def get_comandas(db: Session):
    return db.query(Comanda).all()
```

```python
# ✅ CORRECTO — asyncpg con SQL parametrizado
import asyncpg

async def get_comandas(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch("SELECT id, estado_actual FROM public.comandas WHERE activo = TRUE")
    return [dict(r) for r in rows]
```

**Por qué:** El proyecto usa asyncpg desde el inicio. Mezclar SQLAlchemy rompe el pool de conexiones, el manejo de transacciones y la inyección de dependencias de FastAPI. Las entidades de dominio que hagan falta van como dataclasses en `app/models/`.

---

### 11.2 BackEnd: NO crear archivos `database.py`, `config.py` o `main.py` alternativos

**Problema:** duplicar en otro lugar la funcionalidad que ya existe en `app/core/` y `app/main.py` crea dos fuentes de verdad.

```
# ❌ ARCHIVOS QUE NO DEBEN EXISTIR:
app/database.py       ← ya existe app/core/database.py
app/config.py         ← ya existe app/core/config.py
app/db/database.py    ← duplicado
main.py               ← el entry point es app/main.py, no la raíz
```

Si necesitas la BD o la configuración, importa de `app.core`:

```python
from app.core.database import get_db
from app.core.config import settings
```

---

### 11.3 BackEnd: NO hardcodear usuarios de prueba en el código

**Problema:** diccionarios de usuarios hardcodeados para pruebas terminan siendo una puerta trasera.

```python
# ❌ PROHIBIDO
USERS = {
    "demo": {"password": "123456", "roles": ["admin"]}
}
```

Usa la BD con las migraciones aplicadas y los usuarios de prueba de `sql/seed_local.sql` (ver [`BackEnd/SETUP.md`](BackEnd/SETUP.md)).

---

### 11.4 BackEnd: NO hacer queries SQL en routers ni en services

**Problema:** SQL directamente en el router o en el service rompe la separación de capas.

```python
# ❌ INCORRECTO — SQL en router
@router.get("/comandas")
async def listar(conn = Depends(get_db)):
    return await conn.fetch("SELECT * FROM comandas")  # ← SQL aquí no
```

```python
# ✅ CORRECTO — router llama al service, service llama al repository
@router.get("/comandas")
async def listar(conn = Depends(get_db)):
    return await comanda_service.listar(conn)          # ← así

# service llama repository:
async def listar(conn):
    return await comanda_repository.get_all(conn)      # ← así

# repository tiene el SQL:
async def get_all(conn):
    return await conn.fetch("SELECT * FROM comandas")  # ← solo aquí
```

---

### 11.5 FrontEnd: NO usar `$route` ni `$router` en templates o scripts

**Problema:** `$route` y `$router` en plantillas no son resolvibles por TypeScript en componentes `<script setup>`.

```vue
<!-- ❌ INCORRECTO — $route/$router no tipados en <script setup> -->
<template>
  <div :class="{ active: $route.name === 'dashboard' }" @click="$router.push('/home')">
  </div>
</template>
```

```vue
<!-- ✅ CORRECTO — usar composables -->
<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
</script>

<template>
  <div :class="{ active: route.name === 'dashboard' }" @click="router.push('/home')">
  </div>
</template>
```

---

### 11.6 FrontEnd: NO hacer llamadas HTTP desde componentes o stores directamente con axios

**Problema:** importar axios directamente para hacer requests se salta la autenticación, el refresh y el manejo de errores.

```typescript
// ❌ INCORRECTO — axios directo en un store
import axios from 'axios'

const cargar = async () => {
  const { data } = await axios.get('http://localhost:8000/comandas')  // sin auth, sin manejo de 401
}
```

```typescript
// ✅ CORRECTO — usar apiClient de axiosClient.ts (a través de api/ y services/)
import { apiClient } from '@/api/axiosClient'

const cargar = async () => {
  const { data } = await apiClient.get('/comandas')   // con token, con refresh automático
}
```

---

### 11.7 FrontEnd: NO duplicar scripts en package.json

Antes de añadir o modificar la sección `scripts` de `package.json`, revisar que el script no exista ya. Un script duplicado se pisa en silencio con el último.

---

### 11.8 FrontEnd: NO usar Options API — solo Composition API con `<script setup>`

```vue
<!-- ❌ PROHIBIDO -->
<script lang="ts">
export default {
  data() { return { count: 0 } },
  computed: { double() { return this.count * 2 } },
  methods: { inc() { this.count++ } }
}
</script>
```

```vue
<!-- ✅ SIEMPRE así -->
<script setup lang="ts">
import { ref, computed } from 'vue'

const count = ref(0)
const double = computed(() => count.value * 2)
const inc = () => count.value++
</script>
```

---

### 11.9 Git: NO hacer force push a `develop` o `main`

**Consecuencia:** reescribir el historial de una rama compartida desincroniza todos los clones y complica los merges futuros.

**Regla:** `git push --force` solo es aceptable en ramas personales (`feature/`, `fix/`) que nadie más use. Nunca en `develop` ni en `main`.

---

### 11.10 Git: NO pushear directo a `main` ni a `develop` — todo entra por Pull Request

```
# ❌ INCORRECTO
git checkout develop
git merge feature/mi-modulo && git push      # sin revisión ni CI

# ✅ CORRECTO
git push -u origin feature/mi-modulo
# → abrir un Pull Request hacia develop, esperar el CI y mergear desde ahí
# → para publicar, Pull Request de develop (o release/<version>) hacia main
```

---

### 11.11 NO commitear sin pasar los hooks

Los pre-commit hooks validan lint, formato y tipos. Si un hook falla, el commit se cancela:

```
# ❌ NUNCA hacer esto
git commit --no-verify -m "feat: esto lo revisamos después"
```

Si el hook falla por un error legítimo en tu código, corrígelo. Si falla por un problema de entorno (herramienta no instalada), arregla el entorno; saltarlo solo se acepta con una razón documentada en el commit.

---

## 12. Deuda técnica activa

| ID | Parte | Descripción | Impacto | Urgencia |
|---|---|---|---|---|
| DT-01 | Ambos | No hay pruebas de contrato o de punta a punta entre FrontEnd y BackEnd: las pruebas del FrontEnd simulan la API y las del BackEnd no ejercitan al cliente. | Los contratos de API pueden divergir sin que el CI lo detecte. | Alta |
| DT-02 | BackEnd | Siguen activos caminos de compatibilidad con clientes anteriores: refresh token también en el body (`REFRESH_EN_BODY`), JWT en la URL de los WebSockets (`WS_ACEPTA_JWT`) y la opción de no exigir el token de PIN al confirmar un turno (`EXIGIR_PIN_TOKEN`). | Superficie de ataque mayor de la necesaria; el cliente actual ya usa cookie y ticket. | Media |
| DT-03 | BackEnd | Nombres de archivo inconsistentes en `services/` y `repositories/`: conviven `*_service.py` / `*_repository.py` con nombres sueltos (`estancias.py`, `registros.py`, `chekouts.py`). | Cuesta encontrar el módulo correcto y adivinar dónde va uno nuevo. | Baja |
| DT-04 | FrontEnd | Dos módulos de API para paquetes (`src/api/paquetes.ts` y `src/api/paquetesApi.ts`) con la misma interfaz, y nombres de stores mezclados (`metodos_pago.ts` junto a `turnoCaja.ts`). | Duplicación y confusión sobre cuál importar. | Baja |
| DT-05 | BackEnd | Pendientes del aviso de privacidad: consentimiento expreso para datos de salud, eliminación automática al vencer los plazos de conservación y constancia de consentimiento en reservaciones (detalle en [`BackEnd/docs/aviso-privacidad.md`](BackEnd/docs/aviso-privacidad.md)). | Cumplimiento de la LFPDPPP. | Alta |

---

*Este documento debe actualizarse cuando se tome una decisión arquitectónica que cambie alguna de las secciones anteriores. No es un documento vivo de tareas — para eso usar los issues de GitHub.*
