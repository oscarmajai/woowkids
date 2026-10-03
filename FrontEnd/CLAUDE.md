# CLAUDE.md — Mercury FrontEnd

> **Monorepo:** este archivo vive dentro del monorepo `woowkids`. Las reglas de Git, ramas, PR y releases son las de `../CLAUDE.md`, que tiene prioridad sobre la sección de Git de abajo.

Contexto y reglas para trabajar en este repositorio. Léelo completo antes de empezar cualquier tarea.

## Proyecto

Sistema "todo en uno" para franquicias de restaurantes: check-in, control de inventario y control de restaurante. Aplicación pesada y multi-módulo.

- **Este repo es solo el frontend.** El backend (FastAPI) vive en un repositorio separado. No tienes acceso a él; cuando necesites datos del servidor, asume contratos REST y consúmelos vía la capa de `services`/`api`.
- **Stack:** Vue 3 (Composition API + `<script setup>`) · Vite · Quasar · Pinia · TypeScript · Axios.

## Arquitectura

Organización **por tipo** (la estructura ya existe, respétala):

```
src/
  api/          # Definición de llamadas HTTP (endpoints), instancia de axios
  assets/
  boot/         # Boot files de Quasar (axios, pinia, etc.)
  composables/  # Lógica reutilizable (use*)
  layouts/      # Layouts de Quasar
  pages/        # Vistas/páginas (ruteadas)
  router/       # Configuración de Vue Router
  services/     # Lógica de negocio que orquesta llamadas de api/
  stores/       # Stores de Pinia
  types/        # Tipos e interfaces TypeScript compartidos
  utils/        # Funciones puras de utilidad
```

Reglas de capas:
- Los **componentes/pages** no llaman a axios directo. Consumen `services/` (o `stores/` cuando hay estado).
- `services/` orquesta y llama a `api/`. `api/` solo arma la request y la dispara.
- Tipa todo lo que cruce una frontera (respuestas de API, props, payloads) usando `types/`.
- Estado: **solo Pinia** por ahora. No introducir otras librerías de estado sin pedir confirmación.

## Convenciones de código

- **Componentes Vue:** PascalCase multi-palabra (`CheckinForm.vue`, `InventoryTable.vue`). Siempre `<script setup lang="ts">`.
- **Archivos no-componente (ts):** camelCase (`useInventory.ts`, `authService.ts`, `dateUtils.ts`).
- **Variables, funciones, métodos:** camelCase.
- **Tipos / interfaces / enums:** PascalCase.
- **Constantes globales:** UPPER_SNAKE_CASE.
- Composition API exclusivamente. Nada de Options API.
- TypeScript estricto: evita `any`; usa tipos explícitos en límites de funciones públicas.

## Git — MUY IMPORTANTE

### Push
- **No hagas `git push` por tu cuenta.** Solo pushea cuando el usuario te lo pida explícitamente en ese momento; entonces sí tienes permiso.
- **Nunca pushees a `main`.**
- Si el usuario no ha pedido push, tu trabajo termina en el commit local: dile qué ramas y commits dejaste listos.

### Git Flow
- `main`: producción. No se toca directamente.
- `develop`: rama de integración. **Todas las ramas de trabajo salen de `develop` y se integran de vuelta a `develop` mediante Pull Request en GitHub** (`gh pr create` → `gh pr merge`), no con merges locales. Los conflictos se resuelven en la feature branch (merge de `develop` hacia la rama) antes de mergear el PR.
- Ya no se usa `integration/develop`.
- Ramas de trabajo:
    - `feature/<issue>-<descripcion-corta>` para nuevas funcionalidades.
    - `fix/<issue>-<descripcion-corta>` o `bugfix/...` para correcciones sobre develop.
    - `hotfix/<descripcion>` solo para urgencias sobre `main` (pedir confirmación antes).
    - `release/<version>` para preparar releases.
- `<issue>` es el número de GitHub Issue (ej. `feature/2-registro-entrada`).
- Antes de crear una rama, asegúrate de partir de `develop` actualizado.

### Integración
- Cada rama se integra con su propio PR a `develop`. Antes de mergear el PR,
  actualiza la rama con `develop` (mergea `develop` hacia la feature branch,
  resuelve conflictos ahí, pushea) para que el PR quede sin conflictos.
- Si dos ramas construyeron lo mismo de forma incompatible, la segunda rebasa/
  reimplementa sobre el `develop` ya actualizado; no forzar la resolución.

### Commits — Conventional Commits
- Formato: `<tipo>: <descripción en imperativo>`.
- **Todos los tipos permitidos:** `feat`, `fix`, `chore`, `refactor`, `docs`, `style`, `test`, `perf`, `build`, `ci`, `revert`.
- **Sin scopes** (no usar `feat(checkin):`, solo `feat:`).
- Descripción en minúscula, en imperativo, sin punto final. Ej: `feat: agregar validación de credenciales en login`.
- Si el commit cierra o se relaciona con un issue, referencialo en el cuerpo: `Refs #1` o `Closes #1`.
- **Haz commits frecuentes y atómicos:** un commit por unidad lógica de trabajo terminada. No acumules muchos cambios no relacionados en un solo commit. Cada vez que completes algo coherente, haz commit.
- Elige el tipo según lo que realmente hizo el commit (no marques todo como `feat`).

## Calidad — correr antes de cada commit

Antes de hacer cualquier commit, ejecuta y asegúrate de que pasen:
1. `lint` (ESLint + Prettier)
2. `type-check` (`vue-tsc`)
3. `test` (Vitest), si hay tests que apliquen al cambio

**Si algo falla, NO hagas commit.** Arregla primero, luego commitea. Si no puedes arreglarlo, detente y avísame.

> Nota: estas herramientas (ESLint, Prettier, vue-tsc, Vitest) aún no están todas configuradas en el repo. Si una no existe todavía, avísame en lugar de inventar el comando.

## Flujo de trabajo esperado

1. Para tareas no triviales, primero **explica tu plan** y espera mi visto bueno antes de escribir código.
2. Trabaja una tarea a la vez, enfocado.
3. Crea la rama correcta desde `develop` antes de empezar.
4. Implementa en incrementos pequeños y revisables.
5. Corre lint/type-check/test → commit (conventional) → repite según avances.
6. Al terminar, dime qué ramas y commits dejaste listos. Pushea solo si te lo pedí; si no, los subo yo.
7. Para integrar: abre PR a `develop` con `gh` cuando te lo pida.