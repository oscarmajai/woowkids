# Entorno de desarrollo — FrontEnd

Cómo correr la aplicación en local. Las reglas de Git, commits y calidad están en [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Requisitos

- Node.js `^20.19.0` o `>=22.12.0` (el CI usa Node 22)
- npm
- La API corriendo en `http://localhost:8000` (ver [`BackEnd/SETUP.md`](../BackEnd/SETUP.md))

## 1. Instalación

```bash
cd FrontEnd
npm install
```

`npm install` también instala los hooks de Git de **todo el monorepo** (script `prepare`, carpeta `.husky/`):

- **pre-commit:** revisa solo la parte con archivos en stage. FrontEnd: lint-staged (ESLint + Prettier sobre lo staged) y `vue-tsc`. BackEnd: `ruff` y `mypy` desde `BackEnd/.venv`.
- **commit-msg:** commitlint con Conventional Commits sin scope (`commitlint.config.js`).

## 2. Variables de entorno

```bash
cp .env.example .env.local
```

| Variable            | Descripción                 | Valor en `.env.example`     |
| ------------------- | --------------------------- | --------------------------- |
| `VITE_API_BASE_URL` | URL base del backend (REST) | `http://localhost:8000/api` |
| `VITE_APP_TITLE`    | Título de la aplicación     | `Woow Kids`                 |

El dev server también hace proxy de `/api` (con WebSockets) a `http://127.0.0.1:8000`, o a `VITE_PROXY_TARGET` si está definida. Con `VITE_API_BASE_URL=/api` la app y la API comparten origen, igual que en producción.

En las imágenes Docker estas variables se pasan como argumentos de build (`VITE_API_BASE_URL=/api`).

## 3. Scripts

```bash
npm run dev           # servidor de desarrollo (http://localhost:5173)
npm run build         # build de producción (vue-tsc + vite build)
npm run preview       # previsualizar el build de producción

npm run lint          # ESLint + auto-fix
npm run format        # Prettier sobre src/
npm run type-check    # vue-tsc sin emitir

npm run test          # Vitest (una vez)
npm run test:watch    # Vitest en modo watch
npm run test:coverage # Vitest con cobertura
```

Antes de cada commit deben pasar los mismos comandos que corre el CI:

```bash
npx eslint src && npm run type-check && npx vitest run --dir src
```

## 4. Usuarios de prueba

Con la BD local sembrada (`./scripts/reset_db_local.sh --seed` en `BackEnd/`) se entra con `sistemas@local.dev`, `admin@local.dev` o `cajero@local.dev`, todos con contraseña `12345678`.

## Qué hace cada archivo de configuración

- **eslint.config.js** — Reglas Vue/TS: componentes en PascalCase multi-palabra, fuerza `<script setup>`, advierte sobre `any`, prohíbe `debugger`.
- **.prettierrc.json** — Formato: sin punto y coma, comillas simples, ancho 100, comas finales.
- **vitest.config.ts / vitest.setup.ts** — Tests con jsdom; Quasar y Pinia preinstalados en cada test.
- **commitlint.config.js** — Conventional Commits, todos los tipos, sin scope, subject en minúscula sin punto final.
- **.lintstagedrc.json** — Corre ESLint y Prettier solo sobre los archivos en stage.
- **.husky/** — Hooks pre-commit (calidad) y commit-msg (formato) del monorepo.
- **quasar.config.ts / vite.config.ts** — Plugins de Quasar, paleta de colores, alias `@` → `src/` y proxy de desarrollo.
- **nginx.conf** — Servidor de la imagen de producción.
