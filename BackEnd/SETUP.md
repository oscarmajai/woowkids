# Entorno de desarrollo — BackEnd

Cómo correr la API en local, con PostgreSQL y MinIO en Docker. Las reglas de Git, commits y calidad están en [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Requisitos

- Python 3.12 (mínimo 3.11)
- Docker con Compose
- Cliente `psql` (lo usa `scripts/reset_db_local.sh`)
- Node.js, para los hooks de Git (se instalan desde `FrontEnd/`)

## 1. Entorno virtual y dependencias

```bash
cd BackEnd
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

El hook de pre-commit busca `ruff` y `mypy` en `BackEnd/.venv`: crea el entorno virtual con ese nombre.

## 2. Base de datos y almacenamiento locales

```bash
docker compose -f docker-compose.dev.yml up -d     # PostgreSQL :5433 + MinIO :9000 (consola :9001)
./scripts/reset_db_local.sh --seed                 # migraciones + datos de prueba
```

`reset_db_local.sh` tira el esquema `public` y reaplica **todos** los archivos de `sql/migrations/` en orden. Es la forma de comprobar que una migración nueva funciona desde cero, no solo sobre una BD que ya tiene datos. Sin `--seed` deja la BD solo con los catálogos que siembran las migraciones.

Para tirar todo, incluidos los volúmenes: `docker compose -f docker-compose.dev.yml down -v`

> **MinIO es obligatorio aunque no lo uses.** El `lifespan` de la app llama a `ensure_bucket()` al arrancar; si el endpoint S3 no responde, el arranque se queda en `Waiting for application startup` y **ningún** endpoint contesta, ni siquiera el login.

## 3. Configuración

```bash
cp .env.example .env
```

Los valores de `.env.example` ya apuntan al stack de `docker-compose.dev.yml`. Cambia `SECRET_KEY` por cualquier valor propio.

## 4. Levantar la API

```bash
uvicorn app.main:app --reload
```

- API: `http://localhost:8000/api/...`
- Documentación interactiva: `http://localhost:8000/docs`

El frontend en modo desarrollo (`npm run dev` en `FrontEnd/`) hace proxy de `/api` a este puerto.

### Usuarios de prueba

Los crea `sql/seed_local.sql`, todos con contraseña `12345678`:

| Correo | Rol | Sucursal |
|---|---|---|
| `sistemas@local.dev` | AdministradorSistema | — (acceso global) |
| `admin@local.dev` | Administrador | Sucursal Local |
| `cajero@local.dev` | Cajero | Sucursal Local |

El seed también deja cajas, tarifa de estancia, pulseras, productos y paquetes para probar los flujos completos. **Solo es para desarrollo**: en una instalación real se entra con el administrador inicial (`ADMIN_EMAIL` / `ADMIN_PASSWORD`, ver [`README.md`](../README.md)).

## 5. Pruebas y calidad

```bash
ruff check .            # lint (ruff check . --fix para corregir)
ruff format --check .   # formato (ruff format . para aplicarlo)
mypy app                # tipos
pytest tests/unit       # pruebas unitarias, sin BD
```

Las pruebas de `tests/db/` corren contra un PostgreSQL real y desechable con el esquema completo cargado. Si `TEST_DATABASE_URL` no está definida, se saltan:

```bash
TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/mercury pytest tests/db -q
```

Cada prueba crea sus propios datos con nombres únicos, así que se pueden repetir sobre la misma BD. No apuntes `TEST_DATABASE_URL` a una BD con datos que quieras conservar.

## 6. Migraciones

Al arrancar, `docker/entrypoint.sh` aplica solo las migraciones de `sql/migrations/` que falten (orden byte a byte del nombre) y registra cada una en `public.schema_migraciones`. Una BD vacía se crea con `sql/schema_maestro.sql` y todas quedan registradas. Reglas para una migración nueva:

- **Siguiente número libre** en el prefijo (`NNN_descripcion.sql`, después de la última de `sql/migrations/`).
- **No la edites una vez publicada**: se aplica una sola vez por instalación; un cambio posterior va en otra migración.
- **Sin `BEGIN`/`COMMIT` propios**: el arranque la corre en una transacción junto con su registro. Si falla, no queda a medias ni registrada y el contenedor no arranca (el error queda en los logs).
- **Pruébala desde cero** con `./scripts/reset_db_local.sh`.
- **Regenera el maestro** (`./scripts/generar_schema_maestro.sh`, requiere Docker) y commitéalo con la migración; el CI verifica que esté al día.
- `./scripts/probar_control_migraciones.sh <imagen>` prueba el mecanismo completo de arranque contra un PostgreSQL real (el CI lo corre en cada cambio del backend).

## 7. Respaldos

`scripts/respaldos.py` respalda la BD y los archivos de MinIO. Dentro de los contenedores se usa con el comando `respaldos`:

```bash
respaldos respaldar            # un respaldo ahora
respaldos listar               # respaldos disponibles
respaldos restaurar <nombre>   # vuelve a un respaldo
```

En producción lo corre solo el servicio `respaldos` del `docker-compose.yml` de la raíz (o el proceso equivalente de la imagen todo en uno) cada `BACKUP_CADA_HORAS` horas.
