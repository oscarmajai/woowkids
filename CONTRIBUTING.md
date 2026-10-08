# Cómo contribuir

## Estructura
- `FrontEnd/`: Vue 3 + Quasar. Ver [`FrontEnd/SETUP.md`](FrontEnd/SETUP.md).
- `BackEnd/`: FastAPI + PostgreSQL. Ver [`BackEnd/SETUP.md`](BackEnd/SETUP.md).
- En la raíz:
  - `docker-compose.yml` (stack separado) y `Dockerfile.allinone` + `docker/allinone/` (contenedor único);
  - `.github/` (CI/CD);
  - documentación general (`SAD.md`).

## Git
- Nunca se pushea directo a `main`.
- Git Flow:
  - `main`: producción. Cada llegada a `main` publica un release.
  - `develop`: integración. Toda rama sale de `develop` y vuelve a `develop` por Pull Request.
  - Ramas: `feature/<issue>-<desc>`, `fix/<issue>-<desc>`, `hotfix/<desc>` (sobre `main`), `release/<version>`.
- Un cambio que toca frontend y backend a la vez va en **una sola rama y un solo PR**.
- Commits: Conventional Commits **sin scope** (`feat:`, `fix:`, `chore:`, `refactor:`, `docs:`, `style:`, `test:`, `perf:`, `build:`, `ci:`, `revert:`), en minúscula e imperativo, atómicos. Referencia issues con `Refs #N` / `Closes #N`.
- La versión la calcula el release a partir de los commits desde el último tag:
  - `feat` sube la versión menor;
  - `!:` o `BREAKING CHANGE` sube la mayor;
  - cualquier otro tipo sube el parche.

## Calidad: antes de cada commit
- Frontend (en `FrontEnd/`): `npx eslint src && npm run type-check && npx vitest run --dir src`.
- Backend (en `BackEnd/`): `ruff check . && ruff format --check . && mypy app && pytest tests/unit`.
- Si cambias migraciones: `BackEnd/scripts/generar_schema_maestro.sh` y commitea el maestro.
- El hook de pre-commit corre la parte que cambió. No lo saltes con `--no-verify` salvo una razón documentada en el commit.
- Si algo falla, no hagas commit: arréglalo.
