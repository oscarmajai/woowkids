# SAD — Software Architecture Document
## Sistema Mercury · FEC

**Versión:** 1.1  
**Fecha:** 2026-06-30  
**Autor:** Generado a partir del código en `integration/develop`, ya mergeada y pusheada a `develop` en ambos repos (pendiente promover a `main`)

---

## Tabla de contenidos

1. [Visión general del sistema](#1-visión-general-del-sistema)
2. [Repositorios y estructura de proyecto](#2-repositorios-y-estructura-de-proyecto)
3. [Arquitectura del BackEnd](#3-arquitectura-del-backend)
4. [Arquitectura del FrontEnd](#4-arquitectura-del-frontend)
5. [Base de datos](#5-base-de-datos)
6. [Autenticación y autorización](#6-autenticación-y-autorización)
7. [Comunicación FrontEnd ↔ BackEnd](#7-comunicación-frontend--backend)
8. [Flujo Git e integración de ramas](#8-flujo-git-e-integración-de-ramas)
9. [Calidad de código](#9-calidad-de-código)
10. [Catálogo de módulos](#10-catálogo-de-módulos)
11. [Reglas que NO se deben romper](#11-reglas-que-no-se-deben-romper)
12. [Deuda técnica activa](#12-deuda-técnica-activa)

---

## 1. Visión general del sistema

Mercury es un sistema "todo en uno" para franquicias de restaurantes y centros de entretenimiento familiar (FEC). Gestiona:

- **Check-in y registro de infantes** — control de entrada/salida con RFID
- **Comandas y caja** — punto de venta para cocina y cajero
- **Reservaciones y eventos** — calendario, paquetes, pagos
- **Sucursales y usuarios** — administración multisucursal con roles

El sistema está dividido en dos repositorios independientes que se comunican por HTTP REST:

```
[FrontEnd — Vue 3 + Quasar]  ──HTTP──▶  [BackEnd — FastAPI + PostgreSQL]
  github: sistemasiq/mercurio-frontend      github: sistemasiq/mercurio-backend
```

---

## 2. Repositorios y estructura de proyecto

```
Mercury/
├── SAD.md              ← este documento
├── BackEnd/            ← API REST (Python / FastAPI)
└── FrontEnd/           ← SPA (Vue 3 / Quasar / TypeScript)
```

### BackEnd

```
BackEnd/
├── app/
│   ├── main.py                  # Entry point: crea la app, monta routers, lifespan
│   ├── core/
│   │   ├── config.py            # Settings con pydantic-settings (lee .env)
│   │   ├── database.py          # Pool asyncpg + dependencia get_db
│   │   └── security.py          # JWT, bcrypt, refresh tokens
│   ├── api/
│   │   ├── deps.py              # Dependencias: get_current_user, require_role, require_permission
│   │   └── routers/             # Un archivo por recurso
│   ├── schemas/                 # Modelos Pydantic v2 (request / response, NO son tablas)
│   ├── services/                # Lógica de negocio
│   └── repositories/            # Acceso a BD (SQL crudo con asyncpg)
├── sql/
│   └── migrations/              # Archivos .sql versionados (001_, 002_, …)
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml               # Ruff + mypy + commitlint
└── .env.example
```

### FrontEnd

```
FrontEnd/
├── src/
│   ├── main.ts                  # Entry point Vue
│   ├── boot/
│   │   └── setupPlugins.ts      # Inicializa Quasar, Pinia, router, guards, inactividad
│   ├── api/                     # Llamadas HTTP (solo arma y dispara la request)
│   ├── services/                # Lógica de negocio del cliente (orquesta api/)
│   ├── stores/                  # Estado global con Pinia
│   ├── composables/             # Lógica reutilizable (use*)
│   ├── router/
│   │   ├── index.ts             # Definición de rutas
│   │   └── guards.ts            # Guardias de autenticación y roles
│   ├── layouts/                 # Layouts de Quasar (AuthLayout, MainLayout, SysAdminLayout, AdminLayout)
│   ├── pages/                   # Vistas ruteadas
│   ├── components/              # Componentes reutilizables
│   ├── types/                   # Interfaces y tipos TypeScript compartidos
│   └── utils/                   # Funciones puras de utilidad
├── package.json
├── vite.config.ts
└── tsconfig.json
```

---

## 3. Arquitectura del BackEnd

### 3.1 Stack

| Tecnología | Versión | Uso |
|---|---|---|
| Python | 3.14 | Lenguaje |
| FastAPI | 0.115.x | Framework HTTP |
| asyncpg | 0.31.x | Driver PostgreSQL (async) |
| Pydantic v2 | 2.10.x | Validación y schemas |
| pydantic-settings | 2.7.x | Variables de entorno |
| python-jose | 3.3.x | JWT |
| bcrypt | 5.0.x | Hash de contraseñas |
| Ruff | — | Lint y formato |
| mypy | — | Type checking |

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

### 3.4 Configuración

Toda la configuración viene del archivo `.env` mediante `pydantic-settings`. **Nunca hardcodear** credenciales, URLs de BD, secret keys ni CORS origins en el código.

```python
# app/core/config.py — las Settings se leen de .env automáticamente
class Settings(BaseSettings):
    secret_key: str
    algorithm: str = "HS256"
    database_url: str
    cors_origins: list[str] = ["http://localhost:5173"]
```

Variables requeridas en `.env` (ver `.env.example`):
- `SECRET_KEY` — clave de firma JWT
- `DATABASE_URL` — cadena de conexión PostgreSQL
- `CORS_ORIGINS` — lista separada por comas (opcional en dev)

### 3.5 Entry point y lifespan

El entry point es **`app/main.py`**. No existe `main.py` en la raíz. El lifespan inicializa el pool de conexiones y carga el caché de permisos:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await create_pool()                          # inicializa pool asyncpg
    async with get_pool().acquire() as conn:
        await load_cache(conn)                   # carga permisos en memoria
    yield
    await close_pool()
```

Para correr en desarrollo: `uvicorn app.main:app --reload`

---

## 4. Arquitectura del FrontEnd

### 4.1 Stack

| Tecnología | Versión | Uso |
|---|---|---|
| Vue 3 | 3.5.x | Framework UI |
| TypeScript | 6.x | Lenguaje |
| Quasar | 2.x | Componentes UI + build |
| Pinia | 3.x | Estado global |
| Vue Router | 4.x | Enrutamiento |
| Axios | 1.x | HTTP client |
| Vite | 8.x | Build tool |
| ESLint + Prettier | — | Lint y formato |
| vue-tsc | — | Type checking |
| Vitest | — | Tests unitarios |

### 4.2 Flujo de datos

```
Page / Component
    │  Solo llama a services/ o stores/. Nunca a api/ directamente.
    ▼
Service (src/services/*.ts)
    │  Orquesta llamadas HTTP. Contiene lógica de presentación compleja.
    ▼
API Module (src/api/*.ts)
    │  Solo arma la request y la dispara con axiosClient. Sin lógica.
    ▼
axiosClient (src/api/axiosClient.ts)
    │  Instancia Axios con interceptores de auth y refresh automático.
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

### 4.4 Layouts y enrutamiento

El router define cuatro layouts según el rol del usuario:

| Layout | Ruta base | Roles |
|---|---|---|
| `AuthLayout` | `/login` | Público |
| `MainLayout` | `/home` | Cajero, Cocina, Administrador |
| `SysAdminLayout` | `/sysadmin` | AdministradorSistema |
| `AdminLayout` | `/admin` | Administrador (módulo eventos/reservaciones) |

El guard en `src/router/guards.ts` valida autenticación y roles en cada navegación:

```typescript
// Flujo del guard
// 1. Si requiresAuth y no autenticado → intenta refresh → sino redirige a /login
// 2. Si publicOnly y ya autenticado → redirige al home del rol
// 3. Si meta.roles definido → verifica que el usuario tenga uno de esos roles
```

Siempre definir `meta.requiresAuth` y `meta.roles` en las rutas protegidas:

```typescript
{
  path: 'cocina',
  name: 'cocina',
  component: () => import('@/components/comandas/VisorCocina.vue'),
  meta: { requiresAuth: true, roles: ['Cocina'] as UserRole[], title: 'Visor Cocina' },
}
```

### 4.5 Manejo de errores HTTP

El `axiosClient` tiene interceptores que:
1. Adjuntan el Bearer token a cada request.
2. En un 401: intentan refresh automático una sola vez.
3. Si el refresh falla o no hay refresh token: disparan el evento `auth:unauthorized` → el boot de la app hace logout y redirige a login.
4. Si hay múltiples requests en vuelo durante el refresh: las encolan y reintentan con el nuevo token.

**No re-implementes este flujo** en ningún otro módulo. Todos los módulos usan `apiClient` de `@/api/axiosClient`.

---

## 5. Base de datos

### 5.1 Motor y acceso

- **Motor:** PostgreSQL
- **Driver:** asyncpg (directo, sin ORM)
- **Queries:** SQL parametrizado (`$1`, `$2`, ...)
- **Pool:** inicializado en el lifespan de la app, accesible via `get_pool()`

### 5.2 Esquema base (migration 001)

```
public.usuarios
  id UUID PK | email | password_hash | nombre_completo | rol (enum) | activo | auditoría

public.sucursales
  id UUID PK | nombre | direccion | telefono | activo | clave | auditoría

public.usuarios_sucursal
  id UUID PK | usuario_id FK → usuarios | sucursal_id FK → sucursales | activo | auditoría
```

Todos los IDs son `UUID` generados con `gen_random_uuid()`. Todas las tablas tienen campos de auditoría: `creado`, `creado_por`, `modificado`, `modificado_por`, `activo`.

### 5.3 Roles (enum en BD)

```sql
CREATE TYPE public.rol_tipo AS ENUM (
    'AdministradorSistema',
    'Administrador',
    'Cajero',
    'Cocina'
);
```

- **AdministradorSistema**: acceso global, sin entrada en `usuarios_sucursal`.
- **Administrador**: una o más sucursales asignadas.
- **Cajero / Cocina**: exactamente una sucursal asignada.

### 5.4 Migraciones

Las migraciones son archivos SQL en `sql/migrations/` con prefijo numérico incremental:

```
001_initial_schema.sql         — usuarios, sucursales, usuarios_sucursal
002_token_blacklist.sql        — blacklist de access tokens
003_refresh_tokens.sql         — tabla de refresh tokens
004_roles_permisos.sql         — sistema de permisos granular por rol
005_remove_future_permisos.sql — limpieza de permisos sin endpoints implementados
```

**Regla:** nunca modificar una migración ya aplicada. Siempre crear un archivo nuevo con el siguiente número.

---

## 6. Autenticación y autorización

### 6.1 Flujo de login

```
FrontEnd                           BackEnd
   │                                  │
   │  POST /auth/login                │
   │  { email, password, rememberMe } │
   │ ─────────────────────────────── ▶│
   │                                  │ Verifica credenciales
   │                                  │ Genera access_token (JWT) + refresh_token
   │ ◀─────────────────────────────── │
   │  { token, refreshToken,          │
   │    expiresIn, user }             │
   │                                  │
   │  Guarda en sessionStorage        │
   │  Adjunta Bearer en cada request  │
```

### 6.2 JWT (access token)

**Payload del token:**
```json
{
  "sub": "uuid-del-usuario",
  "email": "usuario@ejemplo.com",
  "role": "Cajero",
  "branch_id": "uuid-de-sucursal",
  "jti": "uuid-único-del-token",
  "iat": 1234567890,
  "exp": 1234571490
}
```

- El `jti` se verifica contra la blacklist en cada request protegida.
- El rol viaja en el token. El backend lo valida en cada endpoint; el frontend lo usa para mostrar/ocultar UI.

### 6.3 Refresh token

- Se genera en login y se almacena hasheado (SHA-256) en la tabla `refresh_tokens`.
- El FrontEnd lo envía al interceptor de Axios en 401 → `POST /auth/refresh`.
- Cada refresh invalida el token anterior y emite uno nuevo (rotación).

### 6.4 Protección de endpoints en el BackEnd

```python
from app.api.deps import require_role, require_permission, get_current_user
from app.schemas.auth import RoleEnum

# Cualquier usuario autenticado
@router.get("/me")
async def me(user: TokenData = Depends(get_current_user)):
    ...

# Solo un rol específico
@router.post("/usuarios")
async def crear(user: TokenData = Depends(require_role(RoleEnum.administrador_sistema))):
    ...

# Por código de permiso (más granular)
@router.delete("/sucursales/{id}")
async def eliminar(user: TokenData = Depends(require_permission("sucursales:eliminar"))):
    ...
```

### 6.5 Protección de rutas en el FrontEnd

```typescript
// En router/index.ts:
meta: { requiresAuth: true, roles: ['AdministradorSistema'] as UserRole[] }

// El guard en router/guards.ts lo verifica automáticamente.
// No añadir lógica de auth en los componentes.
```

### 6.6 Inactividad

La sesión se cierra automáticamente tras 15 minutos de inactividad (configurado en `setupPlugins.ts`). El timer se reinicia con cualquier interacción del usuario.

---

## 7. Comunicación FrontEnd ↔ BackEnd

### 7.1 URL base

Configurada en `.env` del FrontEnd:
```
VITE_API_BASE_URL=http://localhost:8000
```

En producción esta variable apunta al dominio real de la API.

### 7.2 Patrón de módulo API

Cada recurso tiene su propio archivo en `src/api/`:

```typescript
// src/api/usersApi.ts — SOLO arma la request, sin lógica
import { apiClient } from './axiosClient'
import type { User } from '@/types/user'

export const usersApi = {
  list: () => apiClient.get<User[]>('/usuarios').then(r => r.data),
  getById: (id: string) => apiClient.get<User>(`/usuarios/${id}`).then(r => r.data),
  create: (body: CreateUserRequest) => apiClient.post<User>('/usuarios', body).then(r => r.data),
}
```

### 7.3 Proxy de desarrollo

En `vite.config.ts` hay un proxy para evitar CORS en desarrollo local. No se necesita configuración adicional.

---

## 8. Flujo Git e integración de ramas

### 8.1 Estructura de ramas

```
main                ← producción, solo fast-forward desde develop
  └── develop       ← integración validada
        └── integration/develop   ← staging de merges (aquí se resuelven conflictos)
              ├── feature/<issue>-<descripcion>
              ├── fix/<issue>-<descripcion>
              └── hotfix/<descripcion>   (solo urgencias sobre main)
```

### 8.2 Ciclo de vida de una feature

```
1. Crear rama desde develop actualizado:
   git checkout develop && git pull && git checkout -b feature/42-nueva-funcionalidad

2. Desarrollar con commits atómicos y conventional commits.

3. Cuando está lista → hacer merge en integration/develop (nunca directamente a develop).
   git checkout integration/develop
   git merge --no-ff feature/42-nueva-funcionalidad

4. Resolver conflictos en integration/develop.

5. Después de probar → merge integration/develop → develop → main.
```

### 8.3 Orden de integración actual

Ver los CLAUDE.md de cada repo para el orden oficial. El BackEnd se integra antes que el FrontEnd porque el FrontEnd depende de los contratos de la API.

**Estado a 2026-06-30:** `integration/develop` ya fue mergeada a `develop` en ambos repos (BackEnd `3a23f10`, FrontEnd `7216dff`) y `develop` ya fue pusheada a `origin` en ambos. Detalle completo del proceso de integración (commits, conflictos resueltos, deuda técnica cerrada) en `INTEGRACION.md`. Pendiente: testing de integración y promoción `develop` → `main`.

### 8.4 Conventional Commits

Formato obligatorio: `<tipo>: <descripción en minúscula, imperativo, sin punto final>`

| Tipo | Cuándo usarlo |
|---|---|
| `feat` | Nueva funcionalidad |
| `fix` | Corrección de bug |
| `chore` | Tareas de mantenimiento (deps, config, merges) |
| `refactor` | Refactorización sin cambio de comportamiento |
| `docs` | Documentación |
| `style` | Formato, espacios (sin cambio lógico) |
| `test` | Tests |
| `perf` | Mejora de rendimiento |
| `build` | Sistema de build, CI |
| `revert` | Reversión de commit |

```
✅  feat: agregar endpoint de reactivacion de sucursales
✅  fix: corregir validacion de token expirado en guard
✅  chore: merge feature/auth-login en integration/develop
❌  Feat: Agregar endpoint de reactivación de Sucursales.   ← mayúscula, punto final
❌  update stuff                                            ← sin tipo
```

---

## 9. Calidad de código

### BackEnd — correr antes de cada commit

```bash
ruff check . --fix   # lint
ruff format .        # formato
mypy app             # type check
pytest               # tests
```

El pre-commit hook corre ruff, ruff-format y mypy automáticamente. Si alguno falla, el commit se cancela. **Corrige el error, no lo evadas.**

### FrontEnd — correr antes de cada commit

```bash
npm run lint         # ESLint + Prettier
npm run type-check   # vue-tsc
npm run test         # Vitest
```

El pre-commit hook (Husky + lint-staged) corre ESLint, Prettier y vue-tsc automáticamente.

### Reglas de tipo (ambos repos)

- **BackEnd:** type hints obligatorios en toda función pública. No usar `Any` salvo con `# type: ignore` documentado.
- **FrontEnd:** TypeScript estricto. Evitar `any`. Tipar todo lo que cruce una frontera (respuestas API, props, eventos).

---

## 10. Catálogo de módulos

### BackEnd

| Módulo | Router | Service | Repository | Estado |
|---|---|---|---|---|
| Auth | `routers/auth.py` | `auth_service.py` | `user_repo`, `token_repo`, `refresh_token_repo` | ✅ Producción |
| Usuarios | `routers/users.py` | `user_service.py` | `user_repository.py` | ✅ Producción |
| Sucursales | `routers/branches.py` | `branch_service.py` | `branch_repository.py` | ✅ Producción |
| Permisos | `routers/permissions.py` | `permission_service.py` | `permission_repository.py` | ✅ Producción |
| Registro infantes | `api/routers/estancias.py` | `services/estancias.py` | `repositories/estancias.py` + varios | ✅ Producción |
| Comandas | `api/routers/comandas.py` | `comanda_service.py` | `comanda_repository.py` (asyncpg) | ✅ Producción |
| Productos | `api/routers/productos.py` | `producto_service.py` | `producto_repository.py` (asyncpg) | ✅ Producción |
| Eventos/Reservaciones | `api/routers/reservaciones.py` + varios | `services/reservaciones.py` + varios | varios (asyncpg, capas clásicas) | ✅ Producción |

### FrontEnd

| Módulo | Pages | Store | API | Estado |
|---|---|---|---|---|
| Auth / Login | `pages/auth/LoginPage.vue` | `stores/auth.ts` | `axiosClient.ts` | ✅ Producción |
| SysAdmin | `pages/sysadmin/` | `stores/auth.ts` | `usersApi.ts`, `branchesApi.ts` | ✅ Producción |
| Sucursales | `pages/locations/SucursalesPage.vue` + componentes | `stores/sucursales.ts` | `api/sucursales.ts` | ✅ Producción |
| Registro infantes | `pages/RegistrationPage.vue`, `AccessControlPage.vue` | `registration.ts`, `accessControl.ts` | `onboardingClient.ts` | ✅ Producción |
| Comandas / Caja | `components/CajaComponent.vue`, `VisorCocina.vue` | `comandaStore.ts` | `api/` | 🔧 En desarrollo |
| Eventos / Reservaciones | `pages/ReservacionesPage.vue`, `CalendarioPage.vue` | `stores/reservaciones.ts` + varios | `api/reservaciones.ts` + varios | 🔧 En desarrollo |
| Pagos | `pages/PagosPage.vue` | `stores/pagos_reservacion.ts` | `api/pagos_reservacion.ts` | 🔧 En desarrollo |

---

## 11. Reglas que NO se deben romper

Esta sección documenta errores reales encontrados durante la integración de ramas. Cada regla tiene un ejemplo del problema y la solución correcta.

---

### 11.1 BackEnd: NO usar ORM — solo asyncpg con SQL crudo

**Problema encontrado:** `feature/modulo-comandas` importó SQLAlchemy, creó modelos con `Base`, usó `Session` y `db.query(...)`. Esto contradice la arquitectura del proyecto y causa conflictos con el pool asyncpg.

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

**Por qué:** El proyecto usa asyncpg desde el inicio. Mezclar SQLAlchemy rompe el pool de conexiones, el manejo de transacciones y la inyección de dependencias de FastAPI.

> **Estado:** resuelto el 2026-06-30 (commits `634bfa5` y `fb7f169`) — comandas, productos y eventos ya están migrados a asyncpg. La regla se mantiene vigente para evitar que vuelva a introducirse.

---

### 11.2 BackEnd: NO crear archivos `database.py`, `config.py` o `main.py` alternativos

**Problema encontrado:** Varias ramas crearon sus propios `app/database.py`, `app/config.py` y `main.py` (en la raíz) duplicando la funcionalidad ya existente en `app/core/`.

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

> **Estado:** resuelto el 2026-06-30 (commit `aab0173`) — se eliminaron los archivos vestigiales de la raíz de `app/`.

---

### 11.3 BackEnd: NO hardcodear usuarios de prueba en el código

**Problema encontrado:** Algunas ramas incluían diccionarios de usuarios hardcodeados en `main.py` para testing:

```python
# ❌ PROHIBIDO
USERS = {
    "oscarmajai": {"password": "123456", "roles": ["admin"]}
}
```

Usa la BD real con las migraciones aplicadas y los usuarios de prueba documentados en `docs/auth-guide.md`.

---

### 11.4 BackEnd: NO hacer queries SQL en routers ni en services

**Problema encontrado:** Algunas implementaciones pusieron SQL directamente en el router o en el service.

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

**Problema encontrado:** `feature/events` usaba `$route` y `$router` en plantillas Vue, que no son resolvibles por TypeScript en componentes `<script setup>`.

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

**Problema encontrado:** Algunas ramas importaban axios directamente en componentes o stores para hacer requests.

```typescript
// ❌ INCORRECTO — axios directo en un store
import axios from 'axios'

const cargar = async () => {
  const { data } = await axios.get('http://localhost:8000/comandas')  // sin auth, sin manejo de 401
}
```

```typescript
// ✅ CORRECTO — usar apiClient de axiosClient.ts
import { apiClient } from '@/api/axiosClient'

const cargar = async () => {
  const { data } = await apiClient.get('/comandas')   // con token, con refresh automático
}
```

---

### 11.7 FrontEnd: NO duplicar scripts en package.json

**Problema encontrado:** `feature/events` añadió entradas duplicadas en la sección `scripts` de `package.json` (`preview`, `lint`, `format`).

Antes de añadir o modificar `package.json`, revisar que el script no exista ya.

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

**Problema encontrado:** `develop` en el FrontEnd fue force-pusheado al commit inicial, borrando el historial de la rama base.

**Consecuencia:** Todos los forks locales de `develop` quedan desincronizados. Los merges futuros se complican.

**Regla:** `git push --force` solo es aceptable en ramas personales (`feature/`, `fix/`) que nadie más tenga. Nunca en `develop`, `main` ni `integration/develop`.

---

### 11.10 Git: NO mergear directamente a `develop` — usar `integration/develop`

```
# ❌ INCORRECTO
git checkout develop
git merge feature/mi-modulo         # puede introducir conflictos sin control

# ✅ CORRECTO
git checkout integration/develop
git merge --no-ff feature/mi-modulo  # resuelves conflictos aquí
# → después de probar → integration/develop → develop → main
```

---

### 11.11 Ambos repos: NO commitear sin pasar los hooks

Los pre-commit hooks validan lint, formato y tipos. Si un hook falla, el commit se cancela:

```
# ❌ NUNCA hacer esto
git commit --no-verify -m "feat: esto lo revisamos después"
```

Si el hook falla por un error legítimo en tu código, corrígelo. Si el hook falla por un problema de entorno (tool no instalada), repórtalo al equipo — no lo saltes.

---

## 12. Deuda técnica activa

| ID | Repositorio | Descripción | Impacto | Urgencia | Estado |
|---|---|---|---|---|---|
| DT-01 | BackEnd | `app/api/routers/comandas.py` y `productos.py` usaban SQLAlchemy — incompatible con asyncpg | Los endpoints de comandas/productos no funcionaban en producción con el pool actual | Alta | ✅ Resuelta 2026-06-30 (`634bfa5`) |
| DT-02 | BackEnd | Archivos duplicados: `app/database.py`, `app/db/database.py`, `app/config.py`, `app/models.py` (raíz) — vestigios de ramas no limpiadas | Confusión al nuevo desarrollador sobre cuál importar | Media | ✅ Resuelta 2026-06-30 (`aab0173`) |
| DT-03 | BackEnd | El módulo de eventos usaba arquitectura DDD (`domain/`, `application/`, `infrastructure/`) distinta al resto del proyecto | Inconsistencia que dificultaba el mantenimiento | Media | ✅ Resuelta 2026-06-30 (`8dc7bd8`, `fb7f169`) — eliminada la capa DDD, eventos migrado a capas clásicas asyncpg |
| DT-04 | BackEnd | `app/api/router/` (sin 's') y `app/routes/` coexistían con `app/api/routers/` — tres ubicaciones de routers | Confusión sobre dónde va un router nuevo | Media | ✅ Resuelta 2026-06-30 (`644c055`) — todo consolidado en `app/api/routers/` |
| DT-05 | FrontEnd | `src/pages/SucursalesPage.vue` duplica `src/pages/locations/SucursalesPage.vue` | El router apunta a la versión correcta (`locations/SucursalesPage.vue`), pero la otra page queda huérfana sin referencias | Baja | ⚠️ Activa |
| DT-06 | Ambos | No hay tests de integración entre FrontEnd y BackEnd (BackEnd: `tests/` sin archivos más allá de `__init__.py`) | Los contratos de API pueden divergir silenciosamente | Alta | ⚠️ Activa |

Detalle completo de los merges y fixes que cerraron DT-01 a DT-04 en `INTEGRACION.md`.

---

*Este documento debe actualizarse cuando se tome una decisión arquitectónica que cambie alguna de las secciones anteriores. No es un documento vivo de tareas — para eso usar los issues de GitHub.*
