import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Router, RouteRecordRaw } from 'vue-router'

/**
 * B12 / B21 / UX shell: el guard avisa por qué rebota (antes mandaba a Inicio
 * en silencio), una ruta inexistente con sesión muestra un 404 en vez del
 * login y AdministradorSistema sin sucursal no entra a la caja.
 */

const notify = vi.fn()
vi.mock('quasar', async (original) => {
  const real = await original<typeof import('quasar')>()
  return { ...real, Notify: { ...real.Notify, create: (...a: unknown[]) => notify(...a) } }
})

interface AuthFake {
  isAuthenticated: boolean
  currentUser: { id: string; debeCambiarPassword?: boolean } | null
  isSistema: boolean
  currentBranchId: string | null
  permisos: Set<string>
  roles: Set<string>
  hasPermission: (p: string) => boolean
  hasRole: (r: string) => boolean
  tryRefresh: () => Promise<boolean>
}

const auth: AuthFake = {
  isAuthenticated: true,
  currentUser: { id: 'u1' },
  isSistema: false,
  currentBranchId: 'suc-1',
  permisos: new Set(),
  roles: new Set(),
  hasPermission: (p) => auth.permisos.has(p),
  hasRole: (r) => auth.roles.has(r),
  tryRefresh: async () => false,
}

const turno = {
  estaOperando: false,
  asegurarTurnoCargado: vi.fn(),
}

vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/stores/turnoCaja', () => ({ useTurnoCajaStore: () => turno }))
vi.mock('@/stores/accessControl', () => ({
  useAccessControlStore: () => ({ puedeVerPulseras: false, checkoutChild: null }),
}))

const { setupRouterGuards, mensajeSinPermiso, MENSAJE_SIN_TURNO_REGISTRO } =
  await import('@/router/guards')

const Vacio = { template: '<div />' }

const RUTAS: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: Vacio, meta: { publicOnly: true } },
  { path: '/home', name: 'home', component: Vacio, meta: { requiresAuth: true } },
  {
    path: '/cambiar-password',
    name: 'cambiar-password',
    component: Vacio,
    meta: { requiresAuth: true },
  },
  {
    path: '/usuarios',
    name: 'usuarios-listar',
    component: Vacio,
    meta: { requiresAuth: true, permissions: ['usuarios:listar'], title: 'Usuarios' },
  },
  {
    path: '/pos/caja',
    name: 'pos-caja',
    component: Vacio,
    meta: { requiresAuth: true, permissions: ['pos:acceder'], title: 'Caja' },
  },
  {
    path: '/pos/cierre',
    name: 'pos-cierre',
    component: Vacio,
    meta: { requiresAuth: true, permissions: ['pos:acceder'], title: 'Cierre de Caja' },
  },
  {
    path: '/estancias/control-acceso',
    name: 'estancias-control-acceso',
    component: Vacio,
    meta: { requiresAuth: true, permissions: ['estancias:ver_activos'] },
  },
  {
    path: '/estancias/registro-infantes',
    name: 'estancias-registro-infantes',
    component: Vacio,
    meta: {
      requiresAuth: true,
      permissions: ['estancias:checkin'],
      requiresTurno: true,
      title: 'Registro de Entrada',
    },
  },
  {
    path: '/admin/aviso-privacidad',
    name: 'admin-aviso-privacidad',
    component: Vacio,
    meta: { requiresAuth: true, roles: ['AdministradorSistema'], title: 'Aviso de privacidad' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: Vacio,
    meta: { requiresAuth: true },
  },
]

function crearRouter(): Router {
  const router = createRouter({ history: createMemoryHistory(), routes: RUTAS })
  setupRouterGuards(router)
  return router
}

beforeEach(() => {
  notify.mockReset()
  auth.isAuthenticated = true
  auth.currentUser = { id: 'u1' }
  auth.isSistema = false
  auth.currentBranchId = 'suc-1'
  auth.permisos = new Set()
  auth.roles = new Set()
  turno.estaOperando = false
  // Atención no puede consultar el turno: /turnos-caja/activo responde 403.
  turno.asegurarTurnoCargado.mockResolvedValue({ ok: false, error: 'Sin permiso' })
})

describe('guard de permisos (B21)', () => {
  it('avisa por qué no deja entrar en vez de mandar a Inicio en silencio', async () => {
    const router = crearRouter()
    await router.push('/usuarios')

    expect(router.currentRoute.value.name).toBe('home')
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'No tienes permiso para abrir «Usuarios».' }),
    )
  })

  it('sin título usa un mensaje genérico', () => {
    expect(mensajeSinPermiso({ meta: {} })).toBe('No tienes permiso para abrir esa página.')
  })

  it('con permiso no avisa nada', async () => {
    auth.permisos = new Set(['usuarios:listar'])
    const router = crearRouter()
    await router.push('/usuarios')

    expect(router.currentRoute.value.name).toBe('usuarios-listar')
    expect(notify).not.toHaveBeenCalled()
  })

  it('"Nuevo registro" sin turno, para un rol que no abre caja, explica el motivo', async () => {
    auth.permisos = new Set(['estancias:checkin', 'estancias:ver_activos'])
    const router = crearRouter()
    await router.push('/estancias/control-acceso')
    await router.push('/estancias/registro-infantes')

    // Se queda en Control de Acceso (antes rebotaba a Cierre de Caja → Inicio).
    expect(router.currentRoute.value.name).toBe('estancias-control-acceso')
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ message: MENSAJE_SIN_TURNO_REGISTRO }),
    )
  })

  it('el cajero sin turno sigue yendo a Apertura y Cierre', async () => {
    auth.permisos = new Set(['estancias:checkin', 'pos:acceder'])
    const router = crearRouter()
    await router.push('/estancias/registro-infantes')

    expect(router.currentRoute.value.name).toBe('pos-cierre')
  })
})

describe('AdministradorSistema sin sucursal', () => {
  beforeEach(() => {
    auth.isSistema = true
    auth.currentBranchId = null
    auth.permisos = new Set(['pos:acceder'])
  })

  it.each(['/pos/caja', '/pos/cierre'])(
    'no entra a %s y se le pide elegir sucursal',
    async (ruta) => {
      const router = crearRouter()
      await router.push(ruta)

      expect(router.currentRoute.value.name).toBe('home')
      expect(notify).toHaveBeenCalledWith(
        expect.objectContaining({ message: expect.stringContaining('Elige una sucursal') }),
      )
    },
  )

  it('con una sucursal elegida sí entra', async () => {
    auth.currentBranchId = 'suc-1'
    const router = crearRouter()
    await router.push('/pos/caja')

    expect(router.currentRoute.value.name).toBe('pos-caja')
  })
})

describe('ruta inexistente (B12)', () => {
  it('con sesión se queda en la página 404', async () => {
    const router = crearRouter()
    await router.push('/ruta-que-no-existe')

    expect(router.currentRoute.value.name).toBe('not-found')
  })

  it('sin sesión va al login sin guardar la ruta como destino', async () => {
    auth.isAuthenticated = false
    auth.currentUser = null
    const router = crearRouter()
    await router.push('/ruta-que-no-existe')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBeUndefined()
  })
})

describe('rutas de la app (B12)', () => {
  it('el comodín ya no redirige a /login: resuelve a la página 404 con sesión', async () => {
    const { default: router } = await import('@/router')
    const resuelta = router.resolve('/ruta-que-no-existe')

    expect(resuelta.name).toBe('not-found')
    expect(resuelta.meta.requiresAuth).toBe(true)
    expect(resuelta.matched).toHaveLength(2) // AppShell + NotFoundPage
  })
})

describe('contraseña de fábrica pendiente de cambiar', () => {
  beforeEach(() => {
    auth.currentUser = { id: 'u1', debeCambiarPassword: true }
    auth.permisos = new Set(['usuarios:listar'])
  })

  it('manda a cambiarla y recuerda a dónde iba', async () => {
    const router = crearRouter()
    await router.push('/usuarios')

    expect(router.currentRoute.value.name).toBe('cambiar-password')
    expect(router.currentRoute.value.query.redirect).toBe('/usuarios')
  })

  it('desde Inicio no guarda destino', async () => {
    const router = crearRouter()
    await router.push('/home')

    expect(router.currentRoute.value.name).toBe('cambiar-password')
    expect(router.currentRoute.value.query.redirect).toBeUndefined()
  })

  it('ya cambiada deja pasar', async () => {
    auth.currentUser = { id: 'u1', debeCambiarPassword: false }
    const router = crearRouter()
    await router.push('/usuarios')

    expect(router.currentRoute.value.name).toBe('usuarios-listar')
  })
})

describe('rutas solo para un rol (aviso de privacidad)', () => {
  it('un Administrador de sucursal no entra y se le dice por qué', async () => {
    auth.roles = new Set(['Administrador'])
    auth.permisos = new Set(['usuarios:listar', 'cajas:crear'])
    const router = crearRouter()
    await router.push('/admin/aviso-privacidad')

    expect(router.currentRoute.value.name).toBe('home')
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'No tienes permiso para abrir «Aviso de privacidad».' }),
    )
  })

  it('el AdministradorSistema sí entra', async () => {
    auth.roles = new Set(['AdministradorSistema'])
    auth.isSistema = true
    const router = crearRouter()
    await router.push('/admin/aviso-privacidad')

    expect(router.currentRoute.value.name).toBe('admin-aviso-privacidad')
  })

  it('la ruta real exige el rol AdministradorSistema', async () => {
    const { default: router } = await import('@/router')
    expect(router.resolve('/admin/aviso-privacidad').meta.roles).toEqual(['AdministradorSistema'])
  })
})
