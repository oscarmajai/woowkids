# Woow Kids — FrontEnd

Aplicación web del sistema Woow Kids: caja (POS), estancias, eventos y reservaciones, inventario, lealtad, administración multisucursal y portal de padres. Consume la API de [`BackEnd/`](../BackEnd) por REST y WebSockets.

## Stack

- **Vue 3** (Composition API + `<script setup>`)
- **Quasar 2** — componentes UI
- **Vite** — bundler y dev server
- **Pinia** — manejo de estado
- **Vue Router** — rutas con guards de autenticación y permisos
- **TypeScript** — tipado estricto
- **Axios** — cliente HTTP
- **Vitest** + Vue Test Utils — pruebas
- **ESLint + Prettier** — calidad y formato
- **Husky + commitlint** — hooks de Git del monorepo

## Documentación

| Documento                                  | Contenido                                                      |
| ------------------------------------------ | -------------------------------------------------------------- |
| [`SETUP.md`](SETUP.md)                     | Entorno de desarrollo: instalación, variables, scripts y hooks |
| [`GUIA_DESARROLLO.md`](GUIA_DESARROLLO.md) | Convenciones y cómo agregar páginas, módulos de API y stores   |
| [`../SAD.md`](../SAD.md)                   | Arquitectura del sistema completo                              |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Git Flow, commits y calidad                                    |

## Inicio rápido

```bash
npm install
cp .env.example .env.local
npm run dev           # http://localhost:5173 (necesita la API en :8000, ver BackEnd/SETUP.md)
```

## Estructura del proyecto

```
src/
  api/          # Un módulo por recurso; solo arma y dispara la request (axiosClient.ts)
  assets/       # Recursos estáticos
  boot/         # setupPlugins.ts: Quasar, Pinia, router, guards, inactividad
  components/   # Componentes por módulo, ui/ (kit base) y layout/ (sidebar, topbar)
  composables/  # Lógica reutilizable (use*), incluido el menú lateral
  css/          # app.scss: paleta, tipografía y variables CSS
  layouts/      # AuthLayout, AppShell, PublicLayout, PadresLayout
  pages/        # Vistas ruteadas
  router/       # Rutas (index.ts) y guards (guards.ts)
  services/     # Lógica de negocio que orquesta llamadas de api/
  stores/       # Stores de Pinia
  types/        # Tipos e interfaces TypeScript compartidos
  utils/        # Funciones puras de utilidad
```

Las pruebas viven junto al código, en carpetas `__tests__/`.

Reglas de capas:

- Las páginas y componentes consumen `services/` o `stores/`, nunca axios directo.
- `services/` orquesta y llama a `api/`.
- Todo lo que cruce una frontera (respuestas de API, props, payloads) se tipa en `types/`.

## Producción

El `Dockerfile` compila la aplicación y la sirve con nginx (`nginx.conf`), que además hace proxy de `/api` (incluidos los WebSockets) al servicio `backend`. Se construye desde la raíz del monorepo con `docker compose build` (ver [`README.md`](../README.md)).
