# Guía de desarrollo — FrontEnd

Convenciones del código y pasos para agregar funcionalidad. La arquitectura general está en [`SAD.md`](../SAD.md) (secciones 4, 6 y 11) y el entorno en [`SETUP.md`](SETUP.md).

## Nombrado

| Qué                   | Convención                  | Ejemplo                                          |
| --------------------- | --------------------------- | ------------------------------------------------ |
| Componentes Vue       | PascalCase multi-palabra    | `InsumosPage.vue`, `VisorCocina.vue`             |
| Páginas ruteadas      | sufijo `Page`               | `ProveedoresPage.vue`                            |
| Composables           | `use` + camelCase           | `useAppNavigation.ts`                            |
| Módulos de API        | camelCase + `Api`           | `proveedoresApi.ts`                              |
| Services              | camelCase + `Service`       | `proveedorService.ts`                            |
| Stores                | `use` + nombre + `Store`    | `useProveedoresStore` en `stores/proveedores.ts` |
| Variables y funciones | camelCase                   | `cargarProveedores`                              |
| Tipos e interfaces    | PascalCase, sin prefijo `I` | `Proveedor`, `ProveedorCreate`                   |
| Constantes globales   | UPPER_SNAKE_CASE            | `INACTIVITY_MS`                                  |

## Componentes

- Siempre `<script setup lang="ts">`. La Options API está prohibida (regla 11.8 del SAD).
- Rutas con `useRoute()` / `useRouter()`, nunca `$route` / `$router` (regla 11.5).
- Props y emits tipados con `defineProps<...>()` y `defineEmits<...>()`.
- Estilos con `<style scoped>` y las variables CSS de `src/css/app.scss` (`--bg-card`, `--text-primary`, `--border-color`, `--tone-ok-bg`, `--shadow-md`, …) en lugar de colores fijos. La paleta de Quasar (`primary`, `secondary`, `accent`, …) está en `quasar.config.ts` y `app.scss`.
- Antes de crear un componente base, revisa el kit de `src/components/ui/`: `PageHeader`, `DataTableCard`, `TablePager`, `BaseDialog`, `KpiCard`, `StatusBadge` y `StateBlock` (estados de carga, vacío y error).

```vue
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import { useProveedoresStore } from '@/stores/proveedores'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const store = useProveedoresStore()
const activos = computed(() => store.proveedores.filter((p) => p.activo))

onMounted(() => {
  if (auth.currentBranchId) store.cargar(auth.currentBranchId)
})
</script>

<template>
  <q-page padding>
    <PageHeader title="Proveedores" subtitle="Catálogo de la sucursal" />
    <!-- … -->
  </q-page>
</template>
```

## Agregar un recurso nuevo (API → service → store)

1. **Tipos** en `src/types/<recurso>.ts`: la forma de las respuestas y de los payloads.
2. **Módulo de API** en `src/api/<recurso>Api.ts`. Solo arma la request con `apiClient`; nunca importes axios directo (regla 11.6):

   ```typescript
   import { apiClient } from './axiosClient'
   import type { Proveedor, ProveedorCreate } from '@/types/proveedor'

   export const proveedoresApi = {
     listar: (sucursalId: string) =>
       apiClient
         .get<Proveedor[]>('/proveedores', { params: { sucursal_id: sucursalId } })
         .then((r) => r.data),
     crear: (body: ProveedorCreate) =>
       apiClient.post<Proveedor>('/proveedores', body).then((r) => r.data),
   }
   ```

3. **Service** en `src/services/<recurso>Service.ts`: orquesta las llamadas y concentra la lógica que no es de presentación (mapeos, cálculos, combinaciones de varias llamadas).
4. **Store** en `src/stores/<recurso>.ts` cuando el estado se comparte entre pantallas. Guarda `loading` y `error`, y convierte los errores con `mensajeDeError` de `@/utils/errorHandler`.

`apiClient` ya adjunta el token, renueva la sesión ante un 401 y normaliza los errores a `ApiError { statusCode, code, message }`: no repitas ese manejo en los módulos.

## Agregar una página

1. Crea `src/pages/MiRecursoPage.vue`.
2. Registra la ruta en `src/router/index.ts`, dentro del layout que corresponda (`AppShell` para el personal autenticado). Protégela con permisos en `meta`; el guard los valida solo:

   ```typescript
   {
     path: '/mi-recurso',
     component: () => import('@/layouts/AppShell.vue'),
     meta: { requiresAuth: true },
     children: [
       {
         path: '',
         name: 'mi-recurso',
         component: () => import('@/pages/MiRecursoPage.vue'),
         meta: { permissions: ['mi_modulo:ver'], title: 'Mi recurso' },
       },
     ],
   }
   ```

   Otros campos de `meta`: `roles` (solo para lo que el backend restringe por rol), `requiresTurno` (exige turno de caja abierto) y `section` (miga de pan cuando la ruta no está en el menú).

3. Agrega la entrada al menú lateral en `src/composables/useAppNavigation.ts`, con el mismo `routeName` y el `permission` que la oculta a quien no lo tiene:

   ```typescript
   { label: 'Mi recurso', icon: 'inventory_2', routeName: 'mi-recurso', permission: 'mi_modulo:ver' }
   ```

El permiso debe existir en el backend (`GET /api/permisos/catalogo`); si es nuevo, se agrega con una migración en `BackEnd/sql/migrations/`.

## Pruebas

- Vitest + Vue Test Utils con jsdom. `vitest.setup.ts` instala Quasar y Pinia para todos los tests.
- Los archivos van junto al código, en `__tests__/<Nombre>.spec.ts`.
- Prueba la lógica en `utils/`, `services/` y `stores/` sin montar componentes; en componentes y páginas, simula los módulos de `api/` o `services/` con `vi.mock`.

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useProveedoresStore } from '@/stores/proveedores'

vi.mock('@/services/proveedorService', () => ({
  listarProveedores: vi.fn().mockResolvedValue([{ id: '1', nombre: 'Proveedor' }]),
}))

describe('useProveedoresStore', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('carga los proveedores de la sucursal', async () => {
    const store = useProveedoresStore()
    await store.cargar('sucursal-1')
    expect(store.proveedores).toHaveLength(1)
    expect(store.error).toBeNull()
  })
})
```

## Antes de cada commit

```bash
npx eslint src && npm run type-check && npx vitest run --dir src
```

El hook de pre-commit corre lint-staged y `vue-tsc` sobre lo que está en stage; el CI corre además la suite completa y el build. Ver [`CONTRIBUTING.md`](../CONTRIBUTING.md).
