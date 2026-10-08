# Woow Kids — BackEnd

API REST y WebSockets del sistema Woow Kids.

- **Stack:** Python 3.12 · FastAPI · asyncpg · PostgreSQL 16 (SQL crudo, sin ORM) · Pydantic v2 · MinIO.
- **Arquitectura:** por capas, router → service → repository. Solo los repositories escriben SQL. Ver [`SAD.md`](../SAD.md).
- **Migraciones:** SQL versionado en `sql/migrations/`. El contenedor aplica las pendientes al arrancar. Una BD nueva se crea con `sql/schema_maestro.sql`.

## Documentación

| Documento | Contenido |
|---|---|
| [`SETUP.md`](SETUP.md) | Entorno de desarrollo, BD local, migraciones y pruebas |
| [`docs/auth-guide.md`](docs/auth-guide.md) | Autenticación, roles y permisos |
| [`docs/aviso-privacidad.md`](docs/aviso-privacidad.md) | Aviso de privacidad y consentimiento (LFPDPPP) |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Git Flow, commits y calidad |

Con la API levantada, la documentación interactiva de los endpoints está en `http://localhost:8000/docs`.

## Estructura

```
app/            # main.py, core/, api/routers/, schemas/, services/, repositories/, models/, exceptions/
sql/            # migrations/, schema_maestro.sql, seed_local.sql
tests/          # unit/ (sin BD) y db/ (PostgreSQL real)
docker/         # entrypoint.sh y respaldos.sh de la imagen
scripts/        # schema maestro, BD local, prueba de migraciones, respaldos
```
