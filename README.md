# Woow Kids

Sistema todo en uno para franquicias de entretenimiento infantil: caja (POS), estancias con pulseras RFID, eventos y reservaciones, inventario, lealtad y administración multisucursal.

| Carpeta | Qué es | Stack |
|---------|--------|-------|
| [`FrontEnd/`](FrontEnd) | Aplicación web | Vue 3 · Quasar · Pinia · TypeScript · Vite |
| [`BackEnd/`](BackEnd) | API REST y WebSockets | FastAPI · asyncpg · PostgreSQL (SQL crudo) · MinIO |

## Levantar el sistema

### Un solo contenedor (lo más simple)

```bash
docker login ghcr.io        # si el paquete es privado: token con read:packages
docker run -d --name woowkids -p 8080:80 -v woowkids_data:/data ghcr.io/oscarmajai/woowkids:latest
```

Incluye frontend, API, PostgreSQL y MinIO, con todos los datos en el volumen `/data`. La consola de MinIO es opcional: agrega `-p 9001:9001`.

### Contenedores separados (producción)

```bash
docker compose up -d --build
```

| Qué | Dónde |
|-----|-------|
| App | http://localhost:8080 |
| API | http://localhost:8000/docs |
| Consola de MinIO | http://localhost:9001 |

En los dos casos se entra con **`admin@woowkids.com` / `admin1234`**. Los valores por defecto son genéricos: antes de producción copia `.env.example` a `.env` y cámbialos (o pásalos con `-e` al contenedor único). Con `SEED_DEMO=true`, la primera vez se cargan datos de prueba.

La primera vez, el backend crea la base de datos con [`BackEnd/sql/schema_maestro.sql`](BackEnd/sql/schema_maestro.sql), que se genera desde las migraciones de `BackEnd/sql/migrations/`. En cada arranque aplica solo las migraciones que falten y las registra en `schema_migraciones`, así que actualizar es solo cambiar la imagen.

## Imagen publicada (GHCR)

Cada release publica solo `ghcr.io/oscarmajai/woowkids` (todo en uno), con su tag `vX.Y.Z` y `latest`. Los contenedores separados se construyen desde el código con `docker compose`.

## Desarrollo

- Frontend: [`FrontEnd/SETUP.md`](FrontEnd/SETUP.md).
- Backend: [`BackEnd/SETUP.md`](BackEnd/SETUP.md).
- Reglas para trabajar en el repo (Git Flow, commits y calidad): [`CLAUDE.md`](CLAUDE.md).
- Los hooks de Git se instalan con `npm install` dentro de `FrontEnd/`:
  - **commit-msg:** Conventional Commits para todo el repo.
  - **pre-commit:** lint y tipos de la parte que cambió.

## CI/CD

- **`ci.yml`:** en cada push o PR verifica solo la parte que cambió.
  - Frontend: ESLint, vue-tsc, Vitest, build e imagen.
  - Backend: ruff, mypy, pytest, migraciones contra PostgreSQL real, schema maestro e imagen.
- **`release.yml`:** al llegar commits a `main`:
  1. Corre el CI completo.
  2. Calcula la versión con Conventional Commits.
  3. Crea el tag, construye frontend y backend en el runner, publica la imagen todo en uno y crea el GitHub Release.
