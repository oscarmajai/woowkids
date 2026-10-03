# Auditoría QA y de seguridad — Mercury FrontEnd

- **Fecha:** 2026-10-02
- **Rama auditada:** `refactor/UI` (commit `40fc001`)
- **Alcance:** `src/` completo (~40 600 líneas: `api/`, `services/`, `stores/`, `composables/`, `utils/`, `router/`, `boot/`, `layouts/`, `pages/`, `components/`), además de `nginx.conf` y `Dockerfile`.
- **Criterio:** solo bugs, fallos de lógica, errores de runtime, concurrencia y seguridad. Se ignoran estilo, deuda técnica y refactors estéticos.
- **Limitación:** el backend (FastAPI) no está en este repo. Donde el impacto depende de lo que valide el servidor, se indica como **(depende del backend)**. Varios hallazgos de seguridad describen controles que hoy solo existen en el cliente y que el backend **debe** repetir.

## Resumen

| Severidad | Cantidad |
|-----------|----------|
| Crítica   | 2        |
| Alta      | 11       |
| Media     | 23       |
| Baja      | 9        |
| **Total** | **45**   |

| # | Severidad | Título corto |
|---|-----------|--------------|
| 1 | Crítica | El cierre de caja se reporta como exitoso aunque el backend falle |
| 2 | Crítica | Los pagos en efectivo registran el monto recibido (con cambio), no el aplicado |
| 3 | Alta | Ciclo infinito de refresh y reintento ante un 401 persistente |
| 4 | Alta | Checkout: el manejo del 409 (monto cambiado) nunca se ejecuta |
| 5 | Alta | Checkout: método de pago resuelto por nombre en lugar de por tipo |
| 6 | Alta | Puntos de lealtad redimidos en el modal se pierden en varios flujos |
| 7 | Alta | Registro de estancia: UUID de método de pago hardcodeado y monto bruto |
| 8 | Alta | Turno en `BALANCE_REVELADO` tras recargar deja una pantalla sin salida |
| 9 | Alta | La recuperación de `TRANSICION_INVALIDA` en `enviarConteo` es código muerto |
| 10 | Alta | Alta de reservación no atómica: reservaciones huérfanas o duplicadas |
| 11 | Alta | Cierre de evento: pagos secuenciales con fallo parcial llevan a cobrar dos veces |
| 12 | Alta | El logout no limpia los demás stores: los datos pasan al siguiente usuario |
| 13 | Alta | Validación de turno contra un estado que todavía no se ha cargado |
| 14 | Media | Los PIN de autorización quedan confirmados para el siguiente cierre |
| 15 | Media | No se exigen observaciones cuando hay diferencias en el arqueo |
| 16 | Media | El PDF del arqueo se pide con el `turnoId` en vez del `arqueoId` |
| 17 | Media | `cargarTurnoActivo` trata cualquier error como "sin turno" |
| 18 | Media | Errores de precisión flotante bloquean pagos exactos con tarjeta |
| 19 | Media | La cola de refresh nunca se rechaza y hay carrera entre dos refresh |
| 20 | Media | Un timeout en un POST de cobro se reporta como "sin conexión" y se reintenta |
| 21 | Media | `ticket_numero` se repite cada 10 000 ms |
| 22 | Media | Doble clic en un combo crea instancias duplicadas; `splitCombo` pierde unidades |
| 23 | Media | `MetodoPagoMontoForm`: `key` duplicadas entre filas de sistema y manuales |
| 24 | Media | `loadActivos`: rechazo no manejado y división entre cero |
| 25 | Media | Compras: se puede recibir más de lo pendiente y elegir presentaciones de otro insumo |
| 26 | Media | Nueva reservación: el día elegido se traslada al cambiar de mes |
| 27 | Media | Pagos de reservación: se aceptan montos negativos |
| 28 | Media | Cambiar de sucursal (AdministradorSistema) deja datos de la sucursal anterior |
| 29 | Media | La cámara del registro puede quedarse encendida |
| 30 | Media | Visor de fotos: carrera al cerrar que deja blob URLs sin liberar o fotos de otro registro |
| 31 | Media | Portal de padres: código de acceso en la URL y persistido; la sesión nunca caduca en el polling |
| 32 | Media | Tokens en `localStorage` y JWT en la query del WebSocket |
| 33 | Media | La ruta `pos-cierre` no exige permisos |
| 34 | Media | Editar orden: agrupar combos por nombre borra hijos de otras instancias |
| 35 | Media | Historial de ventas: `Promise.all` sin `catch` |
| 36 | Media | `PaymentModal`: consulta de saldo de lealtad con carrera y sin `catch` |
| 37 | Baja | `err instanceof Error` sobre `ApiError` plano oculta el mensaje real |
| 38 | Baja | `horasFacturables` y `horasEvento` fallan al cruzar la medianoche |
| 39 | Baja | El código HTTP 409 se traduce como "sesión expirada" |
| 40 | Baja | La contraseña queda en memoria (`pendingCredentials`) |
| 41 | Baja | `UserFormDialog`: carrera al cambiar de usuario rápido |
| 42 | Baja | `useEstanciasSocket` reintenta para siempre con un token vencido |
| 43 | Baja | `HomePage`: la fecha y el "siguiente evento" no se actualizan |
| 44 | Baja | Alertas de inventario: carrera al cambiar de sucursal |
| 45 | Baja | El botón de descarga del PDF en la pantalla de cierre nunca aparece |

---

## Severidad Crítica

### Bug #1: El cierre de caja se reporta como exitoso aunque el backend falle
- Severidad: Crítica
- Ubicación: `src/components/cierre-caja/AutorizacionCierreModal.vue:295-337` (`finalizarYDescargarPDF`) y `src/stores/turnoCaja.ts:357-380` (`confirmarCierre`)
- Categoría: Lógica
- Descripción del Problema: `turno.confirmarCierre()` atrapa su propio error, lo guarda en `turno.error` y **devuelve `null`; no lanza**. `finalizarYDescargarPDF` no revisa el valor de retorno, así que siempre sigue: cierra el diálogo, muestra "Cierre de caja autorizado correctamente", llama a `reiniciarCicloTurno()` (que además borra `turno.error`) y redirige. El `catch` del componente no se ejecuta nunca.
- Impacto: el cajero cree que cerró la caja, pero el turno sigue `BALANCE_REVELADO` en el servidor. La UI pasa a "sin turno" y deja abrir otro (o falla con un conflicto). El error real no se ve en ningún lado. El arqueo no queda registrado.
- Reproducción / Escenario de Fallo: cortar la red o hacer que `POST /turnos-caja/confirmar` responda 500, y pulsar "Autorizar cierre" con ambos PIN validados. Aparece el toast verde y el formulario de apertura.
- Solución Sugerida:
```ts
// AutorizacionCierreModal.vue
const resultado = await turno.confirmarCierre(obsText, esExtraordinario)
if (resultado === null && turno.error) {
  $q.notify({ type: 'negative', position: 'top', message: turno.error })
  return // no reiniciar el ciclo ni redirigir
}
```
Una alternativa más robusta es que `confirmarCierre` devuelva `{ ok: boolean; pdfUrl }` o vuelva a lanzar el error.

### Bug #2: Los pagos en efectivo registran el monto recibido (con cambio), no el aplicado
- Severidad: Crítica
- Ubicación: `src/components/shared/payments/PaymentModal.vue:404-421` (`agregarPago`) y `:456-471` (`finalizarPago`); los consumidores son `CierreEventoPage.vue:387-412`, `NuevaReservacionPage.vue:1096-1100` y `1286-1295`, `CheckoutPage.vue:286-294`, `OrderSummary.vue` (`onPagoExitoso`) y `CajaComponent.vue:459-463`
- Categoría: Lógica
- Descripción del Problema: en efectivo, el modal guarda en `pago.amount` el **efectivo recibido** (por ejemplo $500 para un saldo de $300) y calcula el cambio solo para mostrarlo. `finalizarPago` emite los montos tal cual. Los consumidores persisten `p.amount` directamente: `pagosReservacionApi.crear({ monto: String(pago.amount) })`, `anticipo: String(montoPagado)`, `pagos: [{ monto: p.amount }]`.
- Impacto: en reservaciones se registran pagos por más de lo cobrado (saldo negativo o "liquidado" en falso), y el arqueo espera $500 en caja cuando solo quedaron $300, lo que genera un faltante ficticio. En checkout el backend exige que `pagos` cubra **exactamente** el cargo, así que todo pago en efectivo con cambio termina en 409. En el registro de estancia y en el POS el resultado depende de si el backend descuenta el cambio **(depende del backend)**.
- Reproducción / Escenario de Fallo: en Cierre de evento con saldo $300, elegir Efectivo, teclear 500, aplicar y confirmar. Se crea `pagos_reservacion.monto = "500"`.
- Solución Sugerida: normalizar en el modal antes de emitir, de modo que el efectivo se ajuste a lo que realmente cubre:
```ts
const finalizarPago = () => {
  const noEfectivo = pagosAplicados.value
    .filter((p) => !esEfectivo(p.method))
    .reduce((s, p) => s + p.amount, 0)
  const pagos = pagosAplicados.value.map((p) =>
    esEfectivo(p.method)
      ? { ...p, amount: Math.round(Math.max(0, totalNeto.value - noEfectivo) * 100) / 100 }
      : { ...p },
  )
  emit('pago-exitoso', pagos.filter((p) => p.amount > 0), /* … */)
  // …
}
```
Si se necesita el efectivo recibido para el ticket, emitirlo en un campo aparte (`recibido`).

---

## Severidad Alta

### Bug #3: Ciclo infinito de refresh y reintento ante un 401 persistente
- Severidad: Alta
- Ubicación: `src/api/axiosClient.ts:114-174` (interceptor de respuesta)
- Categoría: Lógica / Concurrencia
- Descripción del Problema: ante un 401, el interceptor refresca el token y reintenta con `client(config)`. Esa petición vuelve a pasar por el mismo interceptor, y nada marca que ya se reintentó (no hay `_retry`). Si el endpoint responde 401 por una causa que no es la expiración (token revocado para ese recurso, un 401 de negocio fuera de la lista blanca, reloj desfasado), el ciclo refresh → reintento → 401 → refresh se repite sin fin.
- Impacto: bucle de peticiones contra `/auth/refresh` (carga en el backend, posible bloqueo por rate limit), la UI congelada en "cargando" y rotación continua de refresh tokens.
- Reproducción / Escenario de Fallo: un endpoint que siempre responde 401 con un token válido (por ejemplo, un PIN incorrecto en un endpoint nuevo que no está en la lista de `url.includes(...)`).
- Solución Sugerida:
```ts
const config = error.config as InternalAxiosRequestConfig & { _retry?: boolean }
if (status === 401 && !config._retry) {
  config._retry = true
  // …refresh y reintento…
}
// si ya se reintentó: limpiar sesión, emitir auth:unauthorized y rechazar
```

### Bug #4: Checkout: el manejo del 409 (monto cambiado) nunca se ejecuta
- Severidad: Alta
- Ubicación: `src/pages/CheckoutPage.vue:295-341` (`onPagoExtraExitoso`)
- Categoría: Lógica / Runtime
- Descripción del Problema: el código busca `err.response.status === 409` y `err.response.data.detail.totalExtra`. Pero `apiClient` **siempre** rechaza con un `ApiError` plano `{ statusCode, code, message }` (`axiosClient.ts:176`), que no tiene `response`. Además, `extractCodeAndMessage` descarta `horasExtra` y `totalExtra` del `detail`. La rama del 409 es inalcanzable.
- Impacto: cuando avanza el tiempo entre la cotización y el cobro (el caso normal), el modal se cierra con "No se pudo registrar el pago del cargo extra. Error desconocido.", no se actualiza el monto y el cajero no puede completar la salida sin repetir todo el proceso.
- Reproducción / Escenario de Fallo: cotizar, esperar a que cambie la hora facturable y cobrar. El backend responde 409 y se ve un error genérico.
- Solución Sugerida: conservar el `detail` en el `ApiError` (por ejemplo `details?: unknown`) y usarlo:
```ts
// axiosClient.ts
return Promise.reject({ ...buildApiError(status, code, message), details: error.response?.data?.detail })
// CheckoutPage.vue
const apiErr = err as ApiError & { details?: { totalExtra?: number; horasExtra?: number } }
if (apiErr.statusCode === 409 && apiErr.details?.totalExtra !== undefined) { /* … */ }
```

### Bug #5: Checkout: método de pago resuelto por nombre en lugar de por tipo
- Severidad: Alta
- Ubicación: `src/pages/CheckoutPage.vue:184-202` (`mapearMetodoPago`)
- Categoría: Lógica
- Descripción del Problema: `PaymentModal` emite `p.method` con el **valor de categoría** (`'Efectivo'`, `'Tarjeta'`, `'Cupones'`, `'Otro'`; ver `CATEGORIAS_METODO_PAGO`). `CheckoutPage` lo compara contra `m.nombre` del catálogo. El propio tipo documenta que el id "se resuelve por `tipo` … nunca por coincidencia de `nombre`", y así lo hacen `CajaComponent`, `OrderSummary` y `CierreEventoPage`.
- Impacto: si la sucursal nombró el método "Tarjeta de crédito" o "Efectivo MXN", **todo** cobro de tiempo excedente falla con "El método de pago … no está configurado", y el niño no puede hacer checkout con cargo.
- Reproducción / Escenario de Fallo: renombrar el método tipo `T` a "Terminal Banorte" y cobrar un excedente con tarjeta.
- Solución Sugerida:
```ts
const categoria = CATEGORIAS_METODO_PAGO.find((c) => c.valor === nombreMetodo)
const metodo = metodosPagoDisponibles.value.find((m) => m.activo && m.tipo === categoria?.tipo)
```

### Bug #6: Puntos de lealtad redimidos en el modal se pierden en varios flujos
- Severidad: Alta
- Ubicación: `CheckoutPage.vue:286` (`onPagoExtraExitoso(pagos)`), `CierreEventoPage.vue:387` (`onPagoExitoso(pagosAplicados)`) y `NuevaReservacionPage.vue:1096` (`onPagoExitoso(pagos)`)
- Categoría: Lógica
- Descripción del Problema: `PaymentModal` deja redimir puntos (categoría "Lealtad") y baja `totalNeto`, así que los pagos suman `total - descuento`. Estos tres consumidores ignoran los argumentos `celularCliente`, `puntosARedimir` y `descuentoPuntos`.
- Impacto: en checkout los pagos no cubren `totalExtra` y el backend responde 409. En reservaciones queda saldo pendiente igual al descuento, aunque el cliente "ya pagó" con puntos, y los puntos nunca se descuentan. Resultado: dinero o puntos sin conciliar.
- Reproducción / Escenario de Fallo: en Cierre de evento, capturar un celular con saldo, aplicar $50 en puntos y pagar el resto. El saldo del evento queda en $50.
- Solución Sugerida: o bien ocultar la categoría Lealtad en esos flujos (prop `permitirLealtad=false` en `PaymentModal`), o bien enviar `puntos_a_redimir` y `celular` a los endpoints correspondientes. Hoy el modal ofrece algo que esos flujos no pueden procesar.

### Bug #7: Registro de estancia: UUID de método de pago hardcodeado y monto bruto
- Severidad: Alta
- Ubicación: `src/stores/registration.ts:354-356`, `:382-386` y `:138-145`; `src/pages/RegistrationPage.vue:111-120`
- Categoría: Lógica
- Descripción del Problema: `loadMetodoPago()` nunca se llama (no hay ningún uso), así que `metodoPagoId` siempre es `null` y se rellena con el UUID fijo `'b827363b-6453-40e4-9536-f7a004711f91'`, que probablemente solo existe en una base de datos de desarrollo. Ese fallback se usa cuando `pagosFromModal` está vacío: el modal emite `[]` cuando los puntos cubren el total, y entonces se envía `[{ metodoPagoId: <hardcode>, monto: total.value }]`, donde `total` es el **bruto** (sin el descuento por puntos).
- Impacto: en producción el UUID no existe y el registro falla (FK o 422), o se registra un pago fantasma por el total bruto con un método que no es el de la sucursal, además de los puntos redimidos (cobro doble).
- Reproducción / Escenario de Fallo: un tutor con puntos suficientes para cubrir la estancia redime todo y confirma. Se envía un pago por el total con el UUID fijo.
- Solución Sugerida: eliminar el fallback y el UUID. Enviar `pagos: pagosFromModal.value` tal cual (puede ir vacío si los puntos cubren todo) y validar en el cliente que `suma(pagos) + descuento === total`.

### Bug #8: Turno en `BALANCE_REVELADO` tras recargar deja una pantalla sin salida
- Severidad: Alta
- Ubicación: `src/stores/turnoCaja.ts:437-453` (`_aplicarTurno`), `src/pages/CierreCajaPage.vue:28-147` y `AutorizacionCierreModal.vue:265-271`
- Categoría: Lógica
- Descripción del Problema: `_aplicarTurno` solo reabre un diálogo cuando el estado es `ESPERANDO_REVISION`. Si la página se recarga (o el cajero navega y vuelve) con el turno en `BALANCE_REVELADO`, ningún bloque del template coincide (`estaOperando`, `enConteo`, `esperandoRevision` y `estaCerrado` son falsos) y `mostrarDialogAutorizacion` es `false`. El balance (`balancePorMetodo`, `diferenciaNeta`) tampoco se recarga, y `adminEmail` queda vacío, así que `confirmarPinAdmin` cae a `turno.adminNombre || 'admin'` (no es un correo) y la validación del PIN del admin falla siempre.
- Impacto: el turno no se puede cerrar ni cancelar desde la UI. Bloquea la operación de caja hasta que intervenga alguien en la base de datos.
- Reproducción / Escenario de Fallo: autenticar al admin (estado `BALANCE_REVELADO`) y pulsar F5. Solo se ven el encabezado y la barra de pasos.
- Solución Sugerida: en `_aplicarTurno`, si `turno.estado === 'BALANCE_REVELADO'`, abrir `mostrarDialogAutorizacion` y volver a pedir la revisión (o exponer un endpoint `GET` del balance). Persistir `adminEmail` en la respuesta del turno en lugar de depender del estado en memoria.

### Bug #9: La recuperación de `TRANSICION_INVALIDA` en `enviarConteo` es código muerto
- Severidad: Alta
- Ubicación: `src/stores/turnoCaja.ts:246-261` y `src/services/turnoCajaService.ts:135-141`
- Categoría: Lógica
- Descripción del Problema: el servicio envuelve **todo** error en `new Error(mensaje, { cause })`, así que en el store `apiErr.code` siempre es `undefined` y la condición `apiErr.code === 'TRANSICION_INVALIDA'` nunca se cumple. Tampoco sirve el `try/catch` interno: `cargarTurnoActivo()` nunca lanza.
- Impacto: justo el escenario que el comentario describe (recargar en `ESPERANDO_REVISION` y reenviar) muestra un error al cajero en lugar de resincronizar y abrir el modal del admin.
- Reproducción / Escenario de Fallo: enviar el conteo, perder la respuesta (por timeout) y volver a pulsar "Enviar conteo". El backend responde con `TRANSICION_INVALIDA` y se ve un error.
- Solución Sugerida:
```ts
const causa = (err as Error & { cause?: ApiError }).cause
if (causa?.code === 'TRANSICION_INVALIDA' || causa?.statusCode === 409) {
  await cargarTurnoActivo()
  if (esperandoRevision.value) return
}
```

### Bug #10: Alta de reservación no atómica: reservaciones huérfanas o duplicadas
- Severidad: Alta
- Ubicación: `src/pages/NuevaReservacionPage.vue:1196-1311` (`confirmarReservacion`)
- Categoría: Lógica / Concurrencia
- Descripción del Problema: se crea la reservación ya con `estado: 'confirmada'` y `anticipo`, y luego, en bucles secuenciales con `await`, se crean extras, productos y pagos. Si cualquier paso intermedio falla (red, 422 o `mapearMetodoPago` que lanza), la reservación ya existe sin sus partes, y el usuario sigue en el asistente con el botón "Confirmar" habilitado.
- Impacto: al reintentar se crea **otra** reservación completa (duplicado del mismo día y hora), y la primera queda confirmada con `anticipo` declarado sin un registro en `pagos_reservacion`. El anticipo cobrado no queda trazado.
- Reproducción / Escenario de Fallo: desactivar el método de pago tipo `T` después de cobrar el anticipo con tarjeta y confirmar. `mapearMetodoPago` lanza después de crear la reservación y los extras.
- Solución Sugerida: un endpoint transaccional en el backend (`POST /reservaciones/completa`) o, como mínimo, resolver todos los `metodo_pago_id` **antes** de crear nada, y ante un fallo posterior navegar a la reservación creada en lugar de permitir reintentar la creación.

### Bug #11: Cierre de evento: pagos secuenciales con fallo parcial llevan a cobrar dos veces
- Severidad: Alta
- Ubicación: `src/pages/CierreEventoPage.vue:387-412` (`onPagoExitoso`)
- Categoría: Concurrencia / Lógica
- Descripción del Problema: cada pago se crea con un `await` independiente. Si falla el segundo, el primero ya está guardado, pero `cargarTodo()` solo se llama en caso de éxito: `saldoPendiente` en pantalla sigue siendo el original.
- Impacto: el cajero reabre el modal con el saldo completo y vuelve a cobrar lo que ya se registró, con lo que el cliente paga dos veces.
- Reproducción / Escenario de Fallo: pagar con efectivo + tarjeta y hacer fallar el segundo POST. El saldo mostrado no cambia.
- Solución Sugerida: ejecutar `await cargarTodo()` en un `finally` y avisar exactamente qué pagos quedaron registrados. Lo ideal es un endpoint que reciba la lista de pagos en una sola transacción.

### Bug #12: El logout no limpia los demás stores: los datos pasan al siguiente usuario
- Severidad: Alta
- Ubicación: `src/stores/auth.ts:97-106` y `:153-160`; `src/components/layout/AppSidebar.vue:110-113`; `src/boot/setupPlugins.ts:49-58` y `:72-88`
- Categoría: Seguridad
- Descripción del Problema: `logout()` solo limpia el store `auth` y `localStorage`. La navegación a `/login` es SPA (no recarga), así que siguen en memoria `registration` (nombre, teléfono, **fotos de INE** del tutor), `accessControl` (niños activos, `checkoutChild`), `turnoCaja` (turno y credenciales), `lealtad` (saldo por celular), `insumos`, `reservaciones`, etc.
- Impacto: en terminales compartidas (la norma en un POS), el siguiente usuario, incluso de otra sucursal o con menos permisos, ve datos personales del anterior y puede operar sobre su turno hasta que cada página recargue. También se aplica al logout por inactividad.
- Reproducción / Escenario de Fallo: el cajero A captura un registro con INE, sale por inactividad, entra el usuario B y abre Registro: el formulario conserva datos de A (si el componente no se desmontó), o el `turnoCaja` muestra el turno de A en el sidebar.
- Solución Sugerida: un plugin de Pinia que registre `store.$reset` (o una función `resetAll`) y llamarlo en `_clearState()`. La opción más simple y segura es `window.location.assign('/login')` después del logout para descartar todo el estado en memoria.

### Bug #13: Validación de turno contra un estado que todavía no se ha cargado
- Severidad: Alta
- Ubicación: `RegistrationPage.vue:111-118`, `CheckoutPage.vue:141-148`, `NuevaReservacionPage.vue:818-823`, `PagosPage.vue:368-375`, `CierreEventoPage.vue:221-228` y `layouts/AppShell.vue:359-363`
- Categoría: Lógica / Concurrencia
- Descripción del Problema: estas páginas redirigen a `/pos/cierre` si `!turno.estaOperando`, pero nadie garantiza que el turno ya esté cargado. `AppShell` solo llama a `cargarTurnoActivo()` para el rol `Cajero`, y lo hace de forma asíncrona en `onMounted`. Con una recarga directa (F5) en esas rutas, la página evalúa el estado inicial `SIN_TURNO`. Para roles que no son Cajero (Administrador con `reservaciones:gestionar_pagos`), el turno **nunca** se carga, y el guard luego redirige a `pos-historial-arqueos`.
- Impacto: un cajero con turno abierto es expulsado de Registro, Checkout o Nueva reservación tras recargar. Un Administrador nunca puede registrar pagos de reservación desde `PagosPage` ni cobrar el saldo de un evento.
- Reproducción / Escenario de Fallo: abrir `/estancias/registro-infantes` directamente en el navegador con turno abierto. Redirige a cierre.
- Solución Sugerida: exponer en el store una promesa `asegurarTurnoCargado()` (con memo) y esperarla antes de validar, por ejemplo con `beforeEnter` asíncrono en el router. Definir también qué roles deben tener turno para cobrar.

---

## Severidad Media

### Bug #14: Los PIN de autorización quedan confirmados para el siguiente cierre
- Severidad: Media
- Ubicación: `src/components/cierre-caja/AutorizacionCierreModal.vue:219-226` y `:326-327`
- Categoría: Seguridad / Lógica
- Descripción del Problema: `pinCajeroConfirmado`, `pinAdminConfirmado`, `pinCajero`, `pinAdmin` y `observacionesModal` son estado local de un componente que nunca se desmonta mientras se esté en `CierreCajaPage`. Después de un cierre, `reiniciarCicloTurno()` + `router.push` a la **misma** ruta no remonta la página, y nada reinicia esas refs.
- Impacto: si en la misma pantalla se abre un turno nuevo y se cierra (por ejemplo, un turno abierto por error), el modal aparece con ambos PIN "verificados" y permite autorizar sin capturarlos. Es una omisión del control de doble firma **(si el backend no vuelve a validar los PIN en `/confirmar`)**.
- Reproducción / Escenario de Fallo: cerrar el turno 1, abrir el turno 2 en la misma pantalla, iniciar conteo, enviar, autenticar al admin. Los botones de PIN ya están en verde.
- Solución Sugerida: `watch(() => turno.mostrarDialogAutorizacion, (v) => { if (v) resetearFormulario() })`, y que el backend exija un token de validación de PIN de un solo uso en `/confirmar`.

### Bug #15: No se exigen observaciones cuando hay diferencias en el arqueo
- Severidad: Media
- Ubicación: `src/stores/turnoCaja.ts:116` y `:355`; `AutorizacionCierreModal.vue:350-363`
- Categoría: Validación
- Descripción del Problema: el contrato documentado dice "observaciones — requerido si `hayDiferencias`", pero `hayDiferencias` no se usa en ningún componente y `ejecutarAutorizacionCierre` no valida `observacionesModal`.
- Impacto: se cierran turnos con faltante sin ninguna justificación, lo que debilita la auditoría.
- Reproducción / Escenario de Fallo: declarar menos efectivo del esperado y autorizar sin escribir observaciones.
- Solución Sugerida: `if (turno.hayDiferencias && !observacionesModal.value.trim()) { notify(...); return }` y deshabilitar el botón con la misma condición.

### Bug #16: El PDF del arqueo se pide con el `turnoId` en vez del `arqueoId`
- Severidad: Media
- Ubicación: `AutorizacionCierreModal.vue:304-309`, `CierreCajaPage.vue:280-290` y `src/stores/turnoCaja.ts:365-373`
- Categoría: Lógica
- Descripción del Problema: `confirmarCierre` recibe `arqueoId` del backend pero lo descarta (solo devuelve `pdfUrl`). La descarga llama a `GET /turnos-caja/historial/{turnoId}/pdf`, mientras que en `HistorialArqueosPage` el mismo endpoint se usa con el id del **arqueo**.
- Impacto: si `arqueo.id !== apertura.id` **(depende del backend)**, la descarga automática da 404 (el error se traga con `console.warn`) o, peor, descarga el comprobante de otro arqueo.
- Reproducción / Escenario de Fallo: cerrar un turno y revisar la petición de descarga contra el `arqueo_id` de la respuesta.
- Solución Sugerida: devolver y usar `resp.arqueoId` para la descarga.

### Bug #17: `cargarTurnoActivo` trata cualquier error como "sin turno"
- Severidad: Media
- Ubicación: `src/stores/turnoCaja.ts:152-166`
- Categoría: Manejo de errores
- Descripción del Problema: el `catch` pone `SIN_TURNO`, `turnoId = null` y `error = null` ante **cualquier** fallo (red caída, 500, 403), no solo ante el 404 (`TurnoNoEncontradoError`).
- Impacto: con un fallo transitorio, la UI muestra "Sin apertura de caja" y la tarjeta de apertura aunque el turno exista, lo que invita a abrir otro. También se usa después de `registrarRetiro`: un fallo al recargar borra el turno de la vista justo después de un retiro exitoso.
- Reproducción / Escenario de Fallo: con el turno abierto, simular un 500 en `GET /turnos-caja/activo` y recargar.
- Solución Sugerida: solo pasar a `SIN_TURNO` si `err instanceof TurnoNoEncontradoError`. En otro caso, conservar el estado y exponer `error`.

### Bug #18: Errores de precisión flotante bloquean pagos exactos con tarjeta
- Severidad: Media
- Ubicación: `src/components/shared/payments/PaymentModal.vue:277`, `:312-324` y `:334`; `src/components/CajaComponent.vue:303-308`; `src/pages/CierreEventoPage.vue:368-369`
- Categoría: Lógica
- Descripción del Problema: los totales se calculan con aritmética flotante sin redondear. Por ejemplo, `3 × 33.30 = 99.89999999999999`, y la validación `monto > saldoPendiente` rechaza el pago con tarjeta de `99.90` ("No se puede dar cambio en Tarjeta. El máximo es $99.90"). Algo similar pasa con `0.9 - (0.7 + 0.2) = 1.1e-16 > 0`, que deja `saldoPendiente > 0` y deshabilita "Confirmar pago" o "Finalizar evento" mostrando "$0.00".
- Impacto: no se puede cobrar con tarjeta el monto exacto de ciertos tickets, y los eventos quedan sin poder cerrarse.
- Reproducción / Escenario de Fallo: un producto de $33.30 × 3 en la caja, elegir Tarjeta y teclear 99.90.
- Solución Sugerida: trabajar en centavos enteros o redondear en cada cálculo: `const r2 = (n: number) => Math.round(n * 100) / 100`, y comparar con tolerancia (`restante > 0.005`).

### Bug #19: La cola de refresh nunca se rechaza y hay carrera entre dos refresh
- Severidad: Media
- Ubicación: `src/api/axiosClient.ts:140-149` y `:167-173`; `src/router/guards.ts:9-14`; `src/stores/auth.ts:128-143`
- Categoría: Concurrencia
- Descripción del Problema: (a) si el refresh falla, `refreshQueue.length = 0` descarta los callbacks **sin rechazar** sus promesas (`void reject`), así que esas peticiones quedan pendientes para siempre. (b) El guard (`auth.tryRefresh`) y el interceptor refrescan por caminos independientes con el mismo refresh token. Si el backend rota los refresh tokens (devuelve uno nuevo), el segundo refresh usa un token ya invalidado y fuerza el logout.
- Impacto: spinners eternos y memoria retenida, y cierres de sesión aleatorios al navegar justo cuando expira el access token.
- Reproducción / Escenario de Fallo: con el access token vencido, navegar a una ruta protegida mientras la página anterior tiene peticiones en curso.
- Solución Sugerida: guardar `{ resolve, reject }` en la cola y rechazar todo en el `catch`; centralizar el refresh en una sola promesa compartida (`let refreshPromise: Promise<string> | null`) que usen tanto el interceptor como `tryRefresh`.

### Bug #20: Un timeout en un POST de cobro se reporta como "sin conexión" y se reintenta
- Severidad: Media
- Ubicación: `src/utils/errorHandler.ts:46-51`, `src/api/axiosClient.ts:105-109` y `src/components/CajaComponent.vue:428-503`
- Categoría: Concurrencia / Lógica
- Descripción del Problema: `isNetworkError` considera `timeout` (15 s) como "Sin conexión a internet". En un `POST /pagos/completar` lento, el servidor puede haber registrado el pago aunque el cliente aborte. El ticket se queda abierto y el cajero vuelve a cobrar. No hay clave de idempotencia (y `ticket_numero` no sirve como tal; ver #21).
- Impacto: comandas y pagos duplicados, y doble descuento de inventario.
- Reproducción / Escenario de Fallo: latencia superior a 15 s en `/pagos/completar`.
- Solución Sugerida: enviar un `Idempotency-Key` (`crypto.randomUUID()` generado al abrir el modal y reutilizado en los reintentos), distinguir el timeout ("No se confirmó; verifica en el historial antes de reintentar") y subir el timeout en endpoints de cobro.

### Bug #21: `ticket_numero` se repite cada 10 000 ms
- Severidad: Media
- Ubicación: `src/components/CajaComponent.vue:456`
- Categoría: Lógica
- Descripción del Problema: `TICK-${String(Date.now() % 10000).padStart(4, '0')}` solo tiene 10 000 valores posibles y se repite cada 10 segundos, también entre cajas distintas.
- Impacto: folios duplicados en el historial y la cocina. Si el backend tiene una restricción `UNIQUE`, pagos rechazados al azar **(depende del backend)**.
- Reproducción / Escenario de Fallo: dos cajas cobrando con 10 s de diferencia exacta, o un día normal de operación (colisión por cumpleaños casi segura con más de 120 tickets).
- Solución Sugerida: que el backend asigne el folio (secuencia por sucursal) o, como mínimo, usar `crypto.randomUUID()`.

### Bug #22: Doble clic en un combo crea instancias duplicadas; `splitCombo` pierde unidades
- Severidad: Media
- Ubicación: `src/composables/useTicketComanda.ts:76-87` (`agregarCombo`) y `:135-182` (`splitCombo`)
- Categoría: Concurrencia / Manejo de errores
- Descripción del Problema: (a) `agregarCombo` busca `existente` antes del `await obtenerComboHijos`. Dos clics rápidos ven "no existe" y crean **dos** padres con sus hijos. (b) `splitCombo` hace `item.cantidad--` **antes** del `await obtenerComboHijos`. Si la petición falla, la excepción no se maneja (`handleSplitCombo` y `confirmarSplit` no tienen `catch`) y la unidad descontada se pierde del ticket.
- Impacto: tickets con líneas de combo duplicadas o con una unidad menos que lo pedido, y una promesa rechazada sin manejar.
- Reproducción / Escenario de Fallo: doble clic sobre un combo con la red lenta; o dividir un combo con la red caída.
- Solución Sugerida: mantener un `Set<string>` de combos "en expansión" para ignorar clics concurrentes; en `splitCombo`, pedir los hijos primero y decrementar después, dentro de `try/catch`.

### Bug #23: `MetodoPagoMontoForm`: `key` duplicadas entre filas de sistema y manuales
- Severidad: Media
- Ubicación: `src/components/cierre-caja/MetodoPagoMontoForm.vue:117-129` y `src/stores/turnoCaja.ts:460-468`
- Categoría: Lógica / Runtime
- Descripción del Problema: las filas de sistema usan `id: idx + 1` (1, 2, …) y las manuales `nextId++`, que también empieza en 1 (y se reinicia al remontar el componente, aunque las filas manuales sigan en el store). El `v-for` usa `:key="fila.id"`.
- Impacto: keys duplicadas hacen que Vue reutilice el nodo equivocado, y el input de una fila puede mostrar o editar el monto de otra en pleno conteo de caja.
- Reproducción / Escenario de Fallo: un turno con ventas en Tarjeta (fila de sistema `id=1`) más agregar manualmente "Transferencia" (`id=1`).
- Solución Sugerida: usar ids únicos (`crypto.randomUUID()`) tanto en `_aplicarTurno` como en `agregarFila`.

### Bug #24: `loadActivos`: rechazo no manejado y división entre cero
- Severidad: Media
- Ubicación: `src/stores/accessControl.ts:108-116` y `:55-64`
- Categoría: Runtime / Manejo de errores
- Descripción del Problema: (a) cuando el usuario **no** tiene `pulseras:listar`, la rama `else` llama `fetchPulseras` sin `try/catch`. Ese endpoint previsiblemente responde 403 a quien no tiene el permiso, así que `loadActivos()` rechaza, y sus llamadas (`AccessControlPage.vue:124`, `:144` y `:152`, socket y polling) no lo capturan: hay rechazos no manejados cada 15 s en modo fallback. (b) `progressPercent = minutosTranscurridos / minutosPagados`: si `minutosPagados` es 0 (registro de evento o tarifa mal configurada), da `Infinity` o `NaN`.
- Impacto: errores repetidos en consola o en el monitoreo y barras de progreso con `NaN%`. Para Cajero, la lista de pulseras queda vacía y el escaneo RFID marca "no encontrada".
- Reproducción / Escenario de Fallo: entrar a Control de Acceso con un rol sin `pulseras:listar`.
- Solución Sugerida: envolver ambas ramas en `try/catch` (o eliminar la rama `else` si el permiso es obligatorio), y `progressPercent = item.minutosPagados > 0 ? … : 100`.

### Bug #25: Compras: se puede recibir más de lo pendiente y elegir presentaciones de otro insumo
- Severidad: Media
- Ubicación: `src/pages/ComprasPage.vue:785-816` (recepción) y `:532-551` (`unidadesCombinadas` / `onCambiarInsumoLinea`); `src/stores/presentacionesInsumo.ts:27-37`
- Categoría: Validación / Concurrencia
- Descripción del Problema: (a) `hayAlgoQueRecibir` habilita el botón si **alguna** línea es válida, pero `ejecutarRecibir` envía todas las que cumplen `ahora > 0`, incluidas las que tienen `ahora > pendiente` (el `:max` de un `q-input` no impide teclear). (b) `presentacionesStore.items` es global: al cambiar de insumo, la lista del insumo anterior sigue visible hasta que responde `cargarPorInsumo`, las respuestas pueden llegar desordenadas y, si la carga falla, quedan las del insumo anterior.
- Impacto: stock inflado por recepciones por encima de lo pedido **(si el backend no lo valida)**, y líneas de compra con una presentación (factor de conversión) de otro insumo, que corrompen el costo y el stock.
- Reproducción / Escenario de Fallo: pedir 10, teclear 50 en "recibir ahora" en esa línea y 1 en otra válida, y confirmar.
- Solución Sugerida: filtrar `l.ahora > 0 && l.ahora <= l.pendiente` (o bloquear con un error) en el payload; filtrar `presentacionesStore.items` por `insumo_id` e ignorar respuestas obsoletas (comparar con el insumo seleccionado al resolver).

### Bug #26: Nueva reservación: el día elegido se traslada al cambiar de mes
- Severidad: Media
- Ubicación: `src/pages/NuevaReservacionPage.vue:932-951` y `:1207-1210`
- Categoría: Lógica
- Descripción del Problema: `form.selectedDay` guarda solo el **número de día**. El mes y el año salen de `currentMonth` y `currentYear`, que cambian al navegar el calendario. Elegir el 15 de marzo y avanzar a abril para "ver disponibilidad" convierte la fecha en el 15 de abril sin ningún aviso. Tampoco se impide elegir fechas pasadas, y si el día no existe en el nuevo mes (31 → febrero) se genera una fecha inválida (`2026-02-31`).
- Impacto: reservaciones confirmadas en una fecha distinta a la que eligió el cliente, o un error 422.
- Reproducción / Escenario de Fallo: seleccionar el 31, avanzar un mes con 30 días y confirmar.
- Solución Sugerida: guardar la fecha completa (`selectedDate: 'YYYY-MM-DD'`) y deshabilitar los días anteriores a hoy.

### Bug #27: Pagos de reservación: se aceptan montos negativos
- Severidad: Media
- Ubicación: `src/pages/PagosPage.vue:146` y `:381-390`
- Categoría: Validación
- Descripción del Problema: `q-input type="number" min="1"` no impide teclear `-500`. La guarda `!form.monto` solo bloquea 0, vacío o `null`. Tampoco se limita al saldo restante.
- Impacto: pagos negativos que reducen lo pagado o sirven para "devolver" dinero sin control, y sobrepagos **(si el backend no valida)**.
- Reproducción / Escenario de Fallo: capturar `-500` y guardar.
- Solución Sugerida: `const monto = Number(form.value.monto); if (!(monto > 0) || monto > restante) return` y una regla `:rules` equivalente.

### Bug #28: Cambiar de sucursal (AdministradorSistema) deja datos de la sucursal anterior
- Severidad: Media
- Ubicación: `src/stores/auth.ts:48-51`, `src/api/axiosClient.ts:95-98` y páginas que cargan solo en `onMounted` (`CajaComponent.vue:547-556`, `PagosPage.vue:227`, `ComprasPage.vue:436-439`, etc.)
- Categoría: Lógica
- Descripción del Problema: el header `X-Sucursal-Vista` cambia en cuanto se elige otra sucursal, pero los stores y las listas ya cargadas (productos, insumos, reservaciones, métodos de pago) no se vuelven a pedir. `PagosPage` además solo carga `reservaciones` si la lista está vacía.
- Impacto: se arma un ticket o una compra con ids de la sucursal A que se envían en el contexto de la sucursal B (ventas o compras cruzadas, o errores de FK), y los KPIs mezclan sucursales.
- Reproducción / Escenario de Fallo: como AdministradorSistema, abrir Caja en la sucursal A, cambiar a B en el sidebar y cobrar.
- Solución Sugerida: `watch(() => auth.currentBranchId, recargar)` en cada página afectada, o una `key` en el `<router-view>` ligada a `currentBranchId` para remontar la vista.

### Bug #29: La cámara del registro puede quedarse encendida
- Severidad: Media
- Ubicación: `src/components/registro-infantes/TutorForm.vue:44-73`
- Categoría: Recursos / Concurrencia
- Descripción del Problema: `getUserMedia` se resuelve dentro de un `setTimeout`. Si el usuario cierra la cámara (`stopCamera`) o el componente se desmonta antes de que se resuelva, el `stream` se asigna **después** de la limpieza y nunca se detiene. Pulsar dos veces "tomar foto" sobrescribe `streamInstance` y deja el primer stream sin referencia.
- Impacto: la cámara sigue encendida (LED activo y consumo), lo que es un problema de privacidad en el mostrador y deja el dispositivo bloqueado para el siguiente uso.
- Reproducción / Escenario de Fallo: pulsar "Tomar INE" y salir de la página de inmediato.
- Solución Sugerida: un token de intento (`let intento = 0`) y, al resolver, `if (!cameraActive.value || intentoActual !== intento) { stream.getTracks().forEach(t => t.stop()); return }`. Detener cualquier stream previo antes de asignar uno nuevo.

### Bug #30: Visor de fotos: carrera al cerrar que deja blob URLs sin liberar o fotos de otro registro
- Severidad: Media
- Ubicación: `src/components/control-acceso/FotosRegistroDialog.vue:34-54` y `src/api/onboardingClient.ts:21-38`
- Categoría: Recursos / Concurrencia
- Descripción del Problema: si el diálogo se cierra antes de que terminen las descargas, `liberarUrls()` corre primero y luego las promesas asignan URLs nuevas que ya no se liberan. Si se reabre para **otro** niño mientras sigue la carga anterior, la respuesta tardía puede mostrar la INE del registro equivocado. Además, si falla una foto dentro del bucle del ZIP, se pierden las URLs ya creadas.
- Impacto: fuga de memoria con imágenes de identificaciones en blobs, y exposición de la INE de un tutor en el expediente de otro.
- Reproducción / Escenario de Fallo: abrir las fotos del niño A y, antes de que carguen, cerrar y abrir las del niño B.
- Solución Sugerida: capturar `const id = props.registroId` y un contador de solicitud; al resolver, si cambió o el diálogo ya no está abierto, revocar las URLs recibidas y salir.

### Bug #31: Portal de padres: código de acceso en la URL y persistido; la sesión nunca caduca en el polling
- Severidad: Media
- Ubicación: `src/pages/padres/AccessPadrePage.vue:17-33`, `src/pages/padres/DashboardPadrePage.vue:125-155` y `src/stores/padres/padresAuthStore.ts:42-110`
- Categoría: Seguridad
- Descripción del Problema: el código de acceso (que equivale a una credencial) viaja en `?code=` (queda en el historial, los logs del proxy y el header `Referer`), se guarda en claro en `sessionStorage` y se **reenvía** a `/padres/auth` cada 30 s. El `token` que devuelve el backend nunca se usa. `refrescarNinos` traga cualquier error, así que el `catch` de `refrescarSesion` (logout) es inalcanzable: si el código se revoca en el servidor, el padre sigue viendo datos viejos indefinidamente.
- Impacto: reutilización del enlace por terceros con acceso al historial o los logs, y una sesión que no se cierra al revocarse.
- Reproducción / Escenario de Fallo: compartir la pantalla o el historial del navegador; o revocar el código en el backend y observar que el dashboard sigue "activo".
- Solución Sugerida: canjear el código una sola vez por el token, quitarlo de la URL (`router.replace`) y usar el token (con su expiración) en las peticiones siguientes. Propagar el 401 o 403 de `refrescarNinos` para cerrar sesión.

### Bug #32: Tokens en `localStorage` y JWT en la query del WebSocket
- Severidad: Media
- Ubicación: `src/utils/session.ts:8-17`, `src/composables/useComandasSocket.ts:31` y `src/composables/useEstanciasSocket.ts:30`
- Categoría: Seguridad
- Descripción del Problema: el access token y el **refresh token** se guardan en `localStorage`, accesible desde cualquier script, de modo que un solo XSS (por ejemplo, en una dependencia) permite robar una sesión de larga duración. El JWT además viaja en `?token=` del WebSocket, y `nginx.conf` registra las URLs completas en el `access_log` por defecto.
- Impacto: robo de sesión persistente y tokens visibles en los logs de infraestructura.
- Reproducción / Escenario de Fallo: revisar `/var/log/nginx/access.log`, donde aparece `GET /api/comandas/ws?token=eyJ...`.
- Solución Sugerida: refresh token en una cookie `HttpOnly; Secure; SameSite=Strict`; access token en memoria; para el WS, un ticket efímero de un solo uso (`POST /ws-ticket`) o mandar el token en el primer mensaje. Como mitigación inmediata, excluir la query del log de nginx.

### Bug #33: La ruta `pos-cierre` no exige permisos
- Severidad: Media
- Ubicación: `src/router/index.ts:102-106`
- Categoría: Seguridad (autorización)
- Descripción del Problema: `pos-cierre` solo tiene `requiresAuth`, sin `permissions: ['pos:acceder']`. Cualquier rol autenticado (Cocina, Personal de atención) llega a la pantalla de apertura y cierre de caja.
- Impacto: un usuario sin permisos de caja puede intentar abrir turnos o retiros desde la UI **(la protección real depende del backend)**.
- Reproducción / Escenario de Fallo: entrar con un rol de cocina y navegar a `/pos/cierre`.
- Solución Sugerida: `meta: { permissions: ['pos:acceder'], title: 'Cierre de Caja' }`.

### Bug #34: Editar orden: agrupar combos por nombre borra hijos de otras instancias
- Severidad: Media
- Ubicación: `src/components/historial/EditarOrdenModal.vue:130-192`
- Categoría: Lógica
- Descripción del Problema: los hijos se agrupan por `nombre_combo_padre` y el padre se busca por `producto_nombre === comboName`. Una orden con dos líneas padre del mismo combo, o con un producto suelto que se llame igual que el combo, mezcla todos los hijos bajo el primer padre. El segundo padre aparece como "suelto". Seleccionar el combo elimina el primer padre **y los hijos de ambas instancias**.
- Impacto: al quitar un combo de una orden pendiente desaparecen en cocina productos que el cliente sí pagó, o queda un combo sin hijos.
- Reproducción / Escenario de Fallo: cobrar "Combo Kids" en dos líneas distintas (por ejemplo, tras un split) y eliminar uno desde Historial.
- Solución Sugerida: agrupar por `id_combo_padre` (que ya se envía al crear la comanda) o por un id del detalle padre, no por nombre.

### Bug #35: Historial de ventas: `Promise.all` sin `catch`
- Severidad: Media
- Ubicación: `src/components/historial/HistorialView.vue:744-765`
- Categoría: Manejo de errores
- Descripción del Problema: `cargarDatos` encadena `.then().finally()` sin `.catch()`, y además no pasa `signal` a las peticiones, así que el `AbortController` no cancela nada.
- Impacto: un error de red produce un rechazo no manejado, deja la tabla con datos viejos sin avisar y las peticiones "abortadas" siguen consumiendo red.
- Reproducción / Escenario de Fallo: cambiar el filtro con el backend caído.
- Solución Sugerida: pasar `signal` a `obtenerHistorial` y `obtenerEstadisticas`, y agregar `.catch((e) => { if (!signal.aborted) notify(...) })`.

### Bug #36: `PaymentModal`: consulta de saldo de lealtad con carrera y sin `catch`
- Severidad: Media
- Ubicación: `src/components/shared/payments/PaymentModal.vue:250-263` y `src/stores/lealtad.ts:57-60`
- Categoría: Concurrencia / Manejo de errores
- Descripción del Problema: `cargarSaldo` no captura errores (un 404 para un celular sin historial rechaza sin manejo). Si se corrige el número o se cierra el modal antes de la respuesta, la respuesta tardía escribe `saldoDisponible` del celular anterior. Al reabrir el modal (con el celular vacío), puede quedar un saldo obsoleto que permite "redimir" puntos sin cliente.
- Impacto: un descuento aplicado con el saldo de otra persona, y `puntos_a_redimir` enviado sin celular.
- Reproducción / Escenario de Fallo: teclear un celular, borrar un dígito y teclear otro rápido, o cerrar el modal durante la consulta.
- Solución Sugerida: `const consultado = val` y, al resolver, `if (celularCliente.value !== consultado || !props.modelValue) return`. Envolver en `try/catch` y poner `saldoDisponible = 0` en caso de 404.

---

## Severidad Baja

### Bug #37: `err instanceof Error` sobre `ApiError` plano oculta el mensaje real
- Severidad: Baja
- Ubicación: `HistorialView.vue:951`, `EditarOrdenModal.vue:288`, `CheckoutPage.vue:337`, `OrderSummary.vue`, `stores/registroPulseras.ts:74-90`, y los stores con `(error as Error).message ?? '…'` (`insumos.ts:43`, `roles.ts:32`, `sucursales.ts:43`, etc.)
- Categoría: Manejo de errores
- Descripción del Problema: `apiClient` rechaza con objetos planos (`ApiError`), no con instancias de `Error`, y no tienen `response`. Por eso `instanceof Error` es falso y se muestra un texto genérico; `extraerMensajeError` nunca encuentra `response.data`; y `message ?? fallback` no cubre `message === ''`, lo que deja `error = ''` (la UI no muestra nada).
- Impacto: el usuario no ve el motivo real del rechazo ("Stock insuficiente", "Pulsera duplicada").
- Reproducción / Escenario de Fallo: registrar una pulsera duplicada; el mensaje es siempre "Error al registrar la pulsera".
- Solución Sugerida: usar `resolveErrorMessage(err as ApiError)` en todos esos puntos.

### Bug #38: `horasFacturables` y `horasEvento` fallan al cruzar la medianoche
- Severidad: Baja
- Ubicación: `src/utils/horario.ts:3-8` y `src/stores/registration.ts:231-241`
- Categoría: Validación
- Descripción del Problema: con `22:00 → 01:00` la diferencia es negativa y se devuelve 1 hora. Con entradas vacías o mal formadas, `Math.max(1, NaN)` devuelve `NaN`. `horasEvento` ignora los minutos (10:30–12:00 se cuenta como 2 h).
- Impacto: duraciones registradas mal en eventos nocturnos y un `NaN` que puede llegar al payload (`horas_reservadas`).
- Reproducción / Escenario de Fallo: `horasFacturables('22:00', '01:00') === 1`.
- Solución Sugerida: `if (minutos <= 0) minutos += 24 * 60` y validar `Number.isFinite` en cada parte.

### Bug #39: El código HTTP 409 se traduce como "sesión expirada"
- Severidad: Baja
- Ubicación: `src/utils/errorHandler.ts:8`
- Categoría: Lógica
- Descripción del Problema: `409: 'Tu sesión ha expirado…'`. El backend usa 409 para conflictos de negocio (turno, checkout). Cuando el 409 llega sin mensaje, el usuario cree que debe volver a iniciar sesión.
- Impacto: diagnósticos equivocados del usuario.
- Reproducción / Escenario de Fallo: un 409 sin `detail`.
- Solución Sugerida: `409: 'La operación entra en conflicto con el estado actual. Actualiza e intenta de nuevo.'`

### Bug #40: La contraseña queda en memoria (`pendingCredentials`)
- Severidad: Baja
- Ubicación: `src/stores/auth.ts:66-68` y `:153-160`
- Categoría: Seguridad
- Descripción del Problema: cuando el login pide elegir sucursal, `{ email, password }` queda en el store. Si el segundo login falla, no se limpia, y `_clearState()` (logout) tampoco lo borra.
- Impacto: la contraseña en claro es visible con Vue Devtools o en un volcado de memoria de una terminal compartida.
- Reproducción / Escenario de Fallo: un login con selección de sucursal que falla, y luego inspeccionar el store `auth`.
- Solución Sugerida: limpiar `pendingCredentials` en `_clearState`, en el `catch` de `selectBranchAndLogin`, y al expirar un temporizador corto. Mejor aún: que el backend devuelva un token temporal de selección en lugar de reenviar la contraseña.

### Bug #41: `UserFormDialog`: carrera al cambiar de usuario rápido
- Severidad: Baja
- Ubicación: `src/components/usuarios/UserFormDialog.vue:747-785`
- Categoría: Concurrencia
- Descripción del Problema: `cargar()` se dispara con cada cambio de `[show, userId]` y no descarta respuestas viejas. Si `getUser(A)` responde después de `getUser(B)`, el formulario muestra a A mientras `props.userId` es B.
- Impacto: al guardar se sobrescriben el nombre, el correo y el rol de B con los datos de A.
- Reproducción / Escenario de Fallo: abrir la edición de A, cerrar y abrir B de inmediato con la red lenta.
- Solución Sugerida: `const solicitado = props.userId` y, al resolver, `if (props.userId !== solicitado) return`.

### Bug #42: `useEstanciasSocket` reintenta para siempre con un token vencido
- Severidad: Baja
- Ubicación: `src/composables/useEstanciasSocket.ts:47-53`
- Categoría: Recursos
- Descripción del Problema: a diferencia de `useComandasSocket`, no tiene `MAX_INTENTOS_TOTALES`. Si el servidor cierra por token inválido, se reconecta cada 30 s indefinidamente (además del polling de fallback).
- Impacto: ruido en el backend y en los logs (cada intento manda el JWT en la URL; ver #32).
- Reproducción / Escenario de Fallo: dejar Control de Acceso abierto después de que expire la sesión.
- Solución Sugerida: aplicar el mismo tope que en comandas y no reintentar ante los códigos de cierre 1008 o 4401.

### Bug #43: `HomePage`: la fecha y el "siguiente evento" no se actualizan
- Severidad: Baja
- Ubicación: `src/pages/home/HomePage.vue` (`const ahora = new Date()`, `hoyISO`, `siguienteEvento`)
- Categoría: Lógica
- Descripción del Problema: `ahora` y `hoyISO` se fijan al montar, y `siguienteEvento` usa `new Date()` dentro de un `computed` sin ninguna dependencia reactiva, así que nunca se recalcula.
- Impacto: en terminales que permanecen abiertas, "Eventos de hoy" muestra los del día anterior pasada la medianoche, y "siguiente evento" no avanza.
- Reproducción / Escenario de Fallo: dejar el inicio abierto de las 23:50 a las 00:10.
- Solución Sugerida: un `ref` de reloj que se actualice cada minuto y del que dependan los `computed`.

### Bug #44: Alertas de inventario: carrera al cambiar de sucursal
- Severidad: Baja
- Ubicación: `src/layouts/AppShell.vue:375-381` y `src/stores/alertasInventario.ts:28-46`
- Categoría: Concurrencia
- Descripción del Problema: `limpiar()` + `refrescar(nueva)` no cancela una petición en vuelo de la sucursal anterior. Si esta responde después, el badge muestra las alertas de otra sucursal, y el siguiente polling hace sonar el timbre por todas las alertas "nuevas".
- Impacto: badges incorrectos y alertas sonoras falsas.
- Reproducción / Escenario de Fallo: cambiar dos veces de sucursal en menos de 1 s.
- Solución Sugerida: guardar `sucursalId` en el estado y descartar respuestas cuyo `sucursalId` ya no sea el vigente.

### Bug #45: El botón de descarga del PDF en la pantalla de cierre nunca aparece
- Severidad: Baja
- Ubicación: `src/pages/CierreCajaPage.vue:126-145` y `:204`
- Categoría: Lógica
- Descripción del Problema: `pdfUrl` es un `ref(null)` que nunca se asigna (`confirmarCierre` devuelve la URL pero el modal la descarta). Además, `reiniciarCicloTurno()` se ejecuta enseguida, así que la sección `estaCerrado` no llega a mostrarse.
- Impacto: si falla la descarga automática (que se traga con `console.warn`), el cajero no tiene forma de bajar el comprobante desde esa pantalla.
- Reproducción / Escenario de Fallo: un cierre con un error en la descarga automática.
- Solución Sugerida: propagar `pdfUrl` o `arqueoId` desde el modal y avisar con un toast que tenga una acción "Descargar comprobante" cuando la descarga automática falle.

---

## Pruebas de estrés conceptuales aplicadas

Para cada módulo se razonaron estos escenarios:

1. **Entradas límite:** campos vacíos (`""` de `v-model.number`), cero, negativos, notación `1e3`, decimales en campos enteros, montos con más de 2 decimales y fechas inexistentes (31 de febrero).
2. **Aritmética monetaria:** sumas y restas flotantes en totales, cambio, saldo y puntos (`0.1 + 0.2`, `3 × 33.30`).
3. **Concurrencia de UI:** doble clic, respuestas fuera de orden, cerrar un diálogo o desmontar la página con promesas pendientes, cambiar de sucursal o de usuario en pleno vuelo.
4. **Ciclo de sesión:** token vencido durante peticiones paralelas, refresh fallido, logout por inactividad en una terminal compartida, recarga (F5) en cada estado de la máquina de cierre de caja.
5. **Fallos de red:** timeout en POST de cobro, 500 y 409 en cada endpoint de dinero, y fallo parcial en secuencias de varios `await`.
6. **Autorización en el cliente:** rutas sin `permissions`, controles de doble firma que solo viven en el estado del componente, y headers de contexto (`X-Sucursal-Vista`).
7. **Superficie XSS e inyección:** búsqueda de `v-html`, `innerHTML`, `document.write`, `eval` y `new Function`. **No se encontraron**: Vue escapa por defecto toda la interpolación revisada. Tampoco hay construcción de SQL ni ejecución de comandos en el frontend.
8. **Recursos:** blob URLs, `MediaStream`, intervalos, listeners globales y WebSockets.

Las áreas revisadas que no mostraron bugs relevantes fueron `utils/avatar.ts`, `utils/downloadBlob.ts`, `utils/formatoMoneda.ts`, `PaymentKeypad.vue`, `AppliedPaymentsList.vue`, el resto de los stores CRUD simples y los componentes de UI base (`components/ui/*`).
