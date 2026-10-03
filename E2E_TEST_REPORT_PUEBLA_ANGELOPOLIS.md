# Reporte E2E — Flujo completo Mercury (sucursal "Puebla Angelópolis")

Sesión de pruebas manuales vía navegador (Chrome, automatizado), primero como
**AdministradorSistema** y después como **Administrador de sucursal**, contra
el entorno local (Docker), conectado a la BD real compartida del equipo
(`100.125.39.2:5432/mercury`). Backend `http://localhost:8000`, Frontend
`http://localhost:5173`. Rama activa en ambos repos: `fix/bugs-post-integracion`.
Fecha: 2026-07-27.

Capturas de pantalla en [`capturas_e2e_puebla/`](capturas_e2e_puebla/).

## Índice
- [Resumen ejecutivo](#resumen-ejecutivo)
- [Fase 0 — Verificación de entorno](#fase-0)
- [Fase 1 — Sysadmin: recorrido y alta de sucursal](#fase-1)
- [Fase 2 — Admin de sucursal: personal y catálogos](#fase-2)
- [Fase 3 — Flujo operativo completo](#fase-3)
- [Fase 4 — Verificación de permisos por rol](#fase-4)
- [Hallazgos de producto señalados por el usuario](#hallazgos-producto)
- [Plan de ejecución del flujo completo de la app](#plan-de-ejecucion)
- [Qué falta por implementar / gaps](#gaps)
- [Datos creados](#datos-creados)

---

## Resumen ejecutivo

Se replicó de punta a punta el flujo de una franquicia nueva ("Puebla
Angelópolis"): alta de sucursal y administrador desde sysadmin, alta de
personal de los 4 roles, catálogo completo (proveedores, insumos con
presentaciones, productos con receta, combo, paquete, extra, tipo de evento,
método de pago, configuración de lealtad, pulseras), compra con recepción,
reservación con anticipo y captura de celular, intento de check-in de un
niño, venta en Caja mezclando producto suelto + combo, flujo Caja→Cocina, y
verificación cruzada de permisos por rol.

Este ciclo confirma que **7 de los 8 bugs y el hallazgo de diseño del reporte
anterior** ([`E2E_TEST_REPORT.md`](E2E_TEST_REPORT.md), sucursal "Zamora
Plaza", 2026-07-23) ya están corregidos: aislamiento por sucursal en
productos/reservaciones, drift de `pulseras.pulsera_rfid`, edición de
sucursales inactivas, filtro de administrador responsable, maxlength de
pulseras, y el bug de cantidades corruptas en combos de Caja.

Sin embargo, esta sesión encontró **6 bugs nuevos** (3 críticos, 2 altos, 1
medio) y **1 nuevo bug de diseño de esquema** (mismo patrón de drift que ya
había aparecido antes, ahora en otras 2 columnas), más una decisión de
producto explícita del usuario que queda pendiente de implementar:

| # | Severidad | Resumen |
|---|---|---|
| BUG-P01 | Crítica | Crear una sucursal con un teléfono en el formato exacto que sugiere el placeholder del propio formulario (`+52 000 000 0000`, 16 caracteres) provoca un `500` sin manejar — la columna real `sucursales.telefono` es `VARCHAR(15)`. |
| BUG-P02 | Crítica | `productos.nombre` tiene un `UNIQUE` **global** (no por sucursal). Dos franquicias distintas no pueden tener nunca un producto con el mismo nombre (ej. "Agua", "Refresco") — falla con `500` genérico. |
| BUG-P03 | Crítica | Una venta en Caja (combo + producto suelto, con receta definida) marcada "Entregada" en Cocina **no generó ningún movimiento de inventario** — el stock quedó exactamente igual antes y después. |
| BUG-P04 | Alta | El botón "Completar Pago" del Registro de Entrada (check-in de niños) queda **deshabilitado sin ningún aviso** — visualmente idéntico a un botón activo, sin mensaje que indique qué falta (probablemente las fotos de INE/Llegada). Bloquea el check-in por completo. |
| BUG-P05 | Alta | El anticipo de una reservación captura el celular del cliente "para acumular puntos de lealtad" pero **no otorga ningún punto** (verificado en Kardex); la misma pantalla de pago en Caja sí los otorga correctamente. |
| BUG-P06 | Media | El rol semilla "Personal de atención de niños" solo tiene 2 permisos (`estancias:ver_activos`, `pulseras:listar`) — le faltan `estancias:checkin`, `estancias:checkout`, `estancias:gestionar_pagos`, `pulseras:crear/editar`. Con la configuración actual, este rol **no puede hacer check-in de niños**, pese a que es literalmente la función que describe su nombre. |
| BUG-P07 | Media | "Nueva Sucursal" es visible para el rol Administrador (de sucursal) tanto en `/sucursales` como en "Accesos rápidos" del dashboard, pero al hacer clic solo redirige a Inicio sin ningún mensaje — el frontend no oculta acciones que el permiso del usuario no permite. |
| UX-P01 | Media | "Guardar Sucursal" con campos vacíos no da ningún feedback (ni toast ni bordes rojos) — contrasta con "Registrar usuario", que sí valida. |
| UX-P02 | Media | Las tarjetas de "Extras" en el wizard de Nueva Reservación truncan el texto (título, precio, botón) de forma ilegible en 1528px de ancho — 10-11 tarjetas en una sola fila sin wrap. |
| UX-P03 | Alta | El botón "Aplicar Pago" del modal "Pago Multimodal" (Caja y Reservaciones) queda **fuera del viewport y sin scroll accesible** en ventanas de ~667-786px de alto (resoluciones de laptop muy comunes, p.ej. 1366×768) — bloquea cobrar/pagar hasta agrandar la ventana. |
| DRIFT-P01 | Diseño/BD | Mismo patrón de esquema `CHAR(n)` en vez de `VARCHAR(n)` que causó BUG-06 en la sesión anterior reaparece en `reservaciones.telefono_cliente` y `tutores.telefono` (ambas `CHAR(10)`). No causó fallas visibles porque el backend normaliza el teléfono a dígitos antes de guardar en ese flujo — a diferencia de `sucursales.telefono`, donde no hay normalización (ver BUG-P01). |

**Funcionó correctamente (para contraste):** aislamiento por sucursal en
usuarios/proveedores/insumos/productos/paquetes, presentaciones de compra,
compra→recepción→stock, reservación con anticipo (con teléfono normalizado
correctamente), combo mezclado con producto suelto en Caja (cantidades ya NO
se corrompen — BUG-07 de la sesión anterior está resuelto), flujo operativo
Caja→Cocina completo, otorgamiento de puntos de lealtad **en Caja**,
dashboard/reportes correctamente acotados a la sucursal del Administrador, y
permisos de menú/ruta correctos para Cajero y Cocina.

---

## Fase 0 — Verificación de entorno

Backend y frontend arriba en Docker (`mercury-backend-1`, `mercury-frontend-1`),
conectados a la BD real remota (no la de `docker-compose.yml`, que queda sin
usar). Login `admin@oscarmajai.dev` / `12345678` exitoso vía API — **las
credenciales de prueba de `COMO_PROBAR.md` sí funcionan en este entorno**,
contrario a la nota de 2026-07-07 en memoria (desfase ya resuelto).

## Fase 1 — Sysadmin: recorrido y alta de sucursal

Login exitoso, recorrido de Sucursales / Usuarios / Roles / Dashboard sin
errores de consola.

**BUG-P01 (Crítica)** — En "Nueva Sucursal", el campo Teléfono muestra el
placeholder `+52 000 000 0000` (16 caracteres) como formato sugerido. Al
escribir un teléfono con ese mismo formato y guardar, el backend responde
`500 Internal Server Error` con el toast genérico "Error al crear la
sucursal.":

```
asyncpg.exceptions.StringDataRightTruncationError: value too long for type character varying(15)
```

Confirmado en BD: `sucursales.telefono` es `VARCHAR(15)`, pero el propio
placeholder del formulario (con espacios y lada) excede ese límite. Con un
teléfono de 13 caracteres sin espacios sí funciona. Capturas:
[`01-bug-guardar-sucursal-sin-feedback.jpg`](capturas_e2e_puebla/01-bug-guardar-sucursal-sin-feedback.jpg),
[`02-bug-500-telefono-varchar15.jpg`](capturas_e2e_puebla/02-bug-500-telefono-varchar15.jpg).

**UX-P01 (Media)** — Antes de encontrar el bug anterior, se probó guardar el
formulario completamente vacío: el botón "Guardar Sucursal" no hace
absolutamente nada (sin request de red, sin toast, sin bordes rojos). Se
verificó por red/consola que no se dispara ningún request. Contrasta con el
formulario "Registrar usuario" (ver Fase 2), que si se envía sin rol
seleccionado sí marca el campo en rojo con el mensaje "Selecciona un rol".

Se creó la sucursal `SUC-PUE-01` "Puebla Angelópolis" exitosamente tras
corregir el teléfono. Se verificó el filtro de búsqueda de "Administrador
Responsable" (fix de T6 del reporte anterior): escribir "Itzel" filtra
correctamente a los dos administradores que contienen esa subcadena
("Itzel Fernanda Solano", "Itzel Mariana Reyes") — **funciona bien**.

Se creó el usuario Administrador "Ana Regina Ortíz Vela"
(`ana.ortiz@woowkids.dev`) sin sucursal asignada, y se asignó después
editando la sucursal — el flujo de admin multi-sucursal (feature del
2026-07-04) sigue funcionando correctamente.

**Nota (no bug de Mercury):** al abrir "Registrar usuario", el navegador
autocompletó el correo/contraseña del **sysadmin logueado** en los campos de
correo/contraseña del **nuevo usuario a crear** (autofill de Chrome, no del
app). Riesgo operativo real: un administrador que no note el autocompletado
y solo llene nombre+rol podría crear una cuenta duplicada con su propia
contraseña real. Recomendación (frontend, defensivo): usar
`autocomplete="off"`/`"new-password"` y nombres de campo únicos para que los
navegadores no sugieran credenciales guardadas en este formulario.

## Fase 2 — Admin de sucursal: personal y catálogos

Login como `ana.ortiz@woowkids.dev`. Confirmado: sin selector de sucursal
(solo tiene una), header muestra "Puebla Angelópolis" correctamente.

**Personal creado (contraseña `12345678`):**
| Nombre | Correo | Rol |
|---|---|---|
| Marisol Guadalupe Rangel | cajero.puebla@woowkids.dev | Cajero |
| Braulio César Herrera Nava | cocina.puebla@woowkids.dev | Cocina |
| Yolanda Ibarra Cruz | atencion.puebla@woowkids.dev | Personal de atención de niños |

Confirmado: el selector de Rol al crear usuario **no ofrece**
Administrador/AdministradorSistema a un Administrador de sucursal (buen
aislamiento). Ningún selector de sucursal aparece para ningún rol — se
infiere del backend correctamente.

**Catálogo completo creado**, todo correctamente aislado a la sucursal (0
resultados iniciales en cada catálogo, sin fuga de datos de otras
franquicias):
- Proveedor "Distribuidora Angelópolis Alimentos".
- Insumos "Harina de trigo" y "Queso Mozzarella" (base en gramos, compra en
  kilogramos), con presentación "Costal 20kg" para harina.
- Productos "Pizza Individual Angelópolis" (receta: 150g harina + 90g
  queso) y "Refresco Individual Angelópolis", y combo "Combo Pizza y
  Refresco Angelópolis".
- Paquete "Paquete Fiesta Angelópolis" ($3,500, 15 personas, 150 min).
- Extra "Renta de Trampolín Angelópolis" (alcance "Solo esta sucursal").
- Tipo de evento "Festival Angelópolis" (alcance "Solo esta sucursal").
- Método de pago "Efectivo Angelópolis" (alcance "Solo esta sucursal" —
  este catálogo ya no ofrece la opción de crear un método global, commit
  `7e64469`).
- Configuración de lealtad: 5% de retorno, 30 días de caducidad, $1 por
  punto.
- 3 pulseras RFID (`PUE-00001..03`) vía "Registro de Pulseras" — el
  contador `0/50` confirma que T5 del reporte anterior (maxlength de 10 sin
  aviso) está resuelto.

**BUG-P02 (Crítica)** — Al crear el producto "Pizza Individual" (mismo
nombre exacto que el creado en la sucursal "Zamora Plaza" en la sesión
anterior), el backend respondió `500`:

```
asyncpg.exceptions.UniqueViolationError: duplicate key value violates unique
constraint "productos_nombre_key"
DETAIL: Key (nombre)=(Pizza Individual) already exists.
```

Confirmado en BD: `productos_nombre_key` es `UNIQUE (nombre)` sin
`sucursal_id` en la restricción. Esto es un defecto de diseño grave para un
sistema multi-franquicia — cualquier nombre de producto común nunca podrá
repetirse entre sucursales distintas. Se evitó el problema en el resto de la
sesión nombrando los productos con el sufijo "Angelópolis", pero eso no es
una solución real, solo un rodeo para poder continuar probando. Capturas:
[`04-producto-nombre-unico-global.jpg`](capturas_e2e_puebla/04-producto-nombre-unico-global.jpg),
[`04b-producto-nombre-unico-global-toast.jpg`](capturas_e2e_puebla/04b-producto-nombre-unico-global-toast.jpg).

**Nota de datos:** al abrir "Extras" y "Tipos de Evento" en la sucursal
nueva, se vieron listados los catálogos "Global" de sesiones anteriores
(p.ej. "Renta de Trampolín" con descripción "disponible en Zamora Plaza").
Ver sección [Hallazgos de producto](#hallazgos-producto) — el usuario pidió
expresamente eliminar el concepto de alcance global por completo.

## Fase 3 — Flujo operativo completo

**Compra e inventario:** compra a "Distribuidora Angelópolis Alimentos" (1
Costal 20kg de harina + 5kg de queso, $1,400 total), recibida — stock
actualizado correctamente (40,000g harina, 10,000g queso tras sumar al
stock inicial de la creación del insumo).

**Reservación:** "Laura Ximena Torres", Cumpleaños Infantil, 15 de agosto
2026, paquete + extra "Bolsa de Regalo Sorpresa" ($3,560 total), anticipo
30% ($1,068) en efectivo, con celular `2229876543` capturado "para acumular
puntos de lealtad". El teléfono se guardó correctamente truncado a 10
dígitos por el backend (`reservaciones.telefono_cliente` es `CHAR(10)`,
ver DRIFT-P01) — a diferencia de sucursales, aquí el backend sí normaliza el
input antes de guardar, por lo que no hubo error visible.

**UX-P02 (Media)** — En el paso "Paquetes y Extras" del wizard, las 10-11
tarjetas de extras (incluyendo las heredadas de "Zamora Plaza", ver arriba)
se muestran en una sola fila con texto y precios truncados sin elipsis
(`$350.` en vez de `$350.00`, botón "Seleccionar" mostrado como
"eleccion..."). Reproducible en viewport de escritorio estándar (1528px).
Captura: [`05-ux-cards-extras-texto-cortado.jpg`](capturas_e2e_puebla/05-ux-cards-extras-texto-cortado.jpg).

**UX-P03 (Alta)** — Al pagar el anticipo, el modal "Pago Multimodal" no
mostraba el botón "Aplicar Pago" en una ventana de 786px de alto (ni
siquiera con scroll dentro del modal) — solo fue visible tras redimensionar
la ventana del navegador a 950px de alto. Esto es reproducible con **el
mismo componente en Caja**. En un dispositivo con resolución de pantalla
común (1366×768, muy típico en laptops empresariales/POS) el chrome del
navegador deja bastante menos de 786px de alto disponible, por lo que este
bug bloquearía cobrar en producción. Capturas:
[`06-bug-completar-pago-no-hace-nada.jpg`](capturas_e2e_puebla/06-bug-completar-pago-no-hace-nada.jpg)
(nota: nombre de archivo reutilizado del bug de check-in, mismo síntoma
visual de "botón no disponible/no responde").

**Check-in de niños ("Registro de Entrada"):** se completaron los datos del
tutor (Laura Ximena Torres) y del niño (Emilia Torres, 6 años), quedando
"1 guardado" en el resumen con Total a Pagar $0.00. El botón "Completar
Pago" **no reacciona a ningún clic** (probado por coordenadas y por
referencia de elemento) y no dispara ningún request de red.

**BUG-P04 (Alta)** — Inspección del DOM confirmó `disabled="" aria-disabled="true"`
en el botón, pero **visualmente el botón se ve idéntico a un botón activo**
(mismo azul sólido, mismo cursor aparente) — no hay opacidad reducida ni
`cursor: not-allowed` perceptible, y el texto de ayuda ("Asegúrate de
ingresar todos los datos") no dice qué falta. La hipótesis más probable es
que las fotos "Tomar Foto de INE" / "Tomar Foto de Llegada" son
obligatorias pero no lo indican con un asterisco ni ningún otro marcador —
en este entorno de pruebas automatizado no hay cámara disponible para
confirmarlo tomando la foto real, pero el patrón (mismo bloqueo total, sin
mensaje) es idéntico al de BUG-06 de la sesión anterior, solo que ahora el
bloqueo es de UX en vez de un 500. Esto **bloqueó completar el check-in,
vincular pulseras y por lo tanto el checkout de estancia** — igual que en
el reporte anterior, aunque por una causa distinta. Captura:
[`06-bug-completar-pago-no-hace-nada.jpg`](capturas_e2e_puebla/06-bug-completar-pago-no-hace-nada.jpg).

**POS (Caja → Cocina):** se abrió un pedido con Pizza suelta ($95) + Combo
Pizza y Refresco ($115, con Pizza y Refresco como hijos a $0) — al agregar
también un Refresco suelto, el carrito creó una **línea nueva
independiente** en vez de corromper la cantidad del hijo del combo
(confirmado en BD: cada línea de `detalles_comanda` con `cantidad = 1`
exacta). **Esto confirma que BUG-07/BUG-08 de la sesión anterior (cantidad
corrupta al mezclar suelto + combo) está resuelto** a nivel de carrito.

Se cobró el pedido ($230, efectivo, con el mismo celular de Laura) y se
avanzó por Cocina: Pendiente → En Preparación → Listo para Entregar →
Entregado, sin problemas de navegación ni de permisos.

**BUG-P03 (Crítica)** — Pese a que el carrito ya no se corrompe, se
verificó en BD que **ningún movimiento de inventario se generó** para esta
venta, ni al crear la comanda ni después de marcarla "Entregada":
`movimientos_inventario` solo contiene los 2 movimientos de la compra
recibida en la Fase anterior — cero movimientos de tipo salida/venta para
Harina de trigo o Queso Mozzarella, pese a que la Pizza Individual (vendida
2 veces: 1 suelta + 1 dentro del combo) tiene receta definida (150g harina
+ 90g queso cada una, se esperaban 300g/180g de descuento). Captura:
[`07-venta-entregada-sin-descuento-inventario.jpg`](capturas_e2e_puebla/07-venta-entregada-sin-descuento-inventario.jpg).

**Puntos de lealtad:** el pago en Caja con el celular de Laura otorgó
correctamente **+12 puntos** ($230 × 5% = $11.50 → redondeado, escalado por
`valor_punto`, ver fix `1bd9901`), visibles en el Kardex de Lealtad.

**BUG-P05 (Alta)** — Al revisar el Kardex de Laura, **solo aparece el
movimiento de la venta en Caja** — el anticipo de $1,068 pagado antes en la
reservación (con el mismo celular, en la misma pantalla "Pago Multimodal"
con el mismo texto "Para acumular puntos de lealtad") **no generó ningún
punto**, pese a que se esperarían ~53 puntos adicionales (5% de $1,068).
Esto es una inconsistencia real entre dos flujos que comparten el mismo
componente de UI y la misma promesa al usuario.

## Fase 4 — Verificación de permisos por rol

Se inició sesión con cada uno de los 4 usuarios creados y se confirmó:

| Rol | Menú visible | Acceso directo a ruta ajena (`/usuarios`, `/estancias/registro-infantes`, etc.) |
|---|---|---|
| Cajero (Marisol) | Caja, Control de Acceso, Historial, Eventos, Kardex de Lealtad | Redirige a Inicio — correcto |
| Cocina (Braulio) | Solo Cocina | — |
| Personal de atención de niños (Yolanda) | Solo Control de Acceso, Pulseras | Redirige a Inicio incluso para `/estancias/registro-infantes` — **ver BUG-P06** |
| Administrador (Ana) | Todo lo de su sucursal (sin Sucursales/Usuarios/Roles de otras franquicias) | Dashboard y Sucursales correctamente acotados a 1 sucursal / 3 usuarios |

**BUG-P06 (Media, hallazgo de datos/configuración)** — Antes de hacer login
como Yolanda, se revisó el rol "Personal de atención de niños" en
`/roles` (como sysadmin): tiene únicamente **2 permisos activos**
("Ver niños en estancia activa" y "Listar pulseras e inventario"), pese a
que su propia descripción de rol dice *"Registra entradas/salidas de niños
y cobra estancias en el módulo de Estancias."* Le faltan, como mínimo:
"Registrar entrada de niños", "Registrar salida de niños", "Registrar
pagos extra de estancia" (categoría Estancias) y "Registrar pulseras
nuevas"/"Editar pulseras" (categoría Pulseras). Se confirmó en vivo:
Yolanda no ve ninguna opción de check-in en su menú, y al navegar
directamente a `/estancias/registro-infantes` es redirigida a Inicio sin
ningún mensaje. **Con la configuración de permisos actual de este rol en la
base de datos, el personal de atención de niños simplemente no puede
hacer su trabajo.** Capturas:
[`03-rol-atencion-ninos-permisos-incompletos.jpg`](capturas_e2e_puebla/03-rol-atencion-ninos-permisos-incompletos.jpg),
[`08-rol-atencion-ninos-sin-acceso-checkin.jpg`](capturas_e2e_puebla/08-rol-atencion-ninos-sin-acceso-checkin.jpg).

**BUG-P07 (Media)** — Como Ana (Administrador), el botón "+ Nueva
Sucursal" es visible tanto en `/sucursales` como en "Accesos rápidos" del
Dashboard (`/reportes/dashboard`). Al hacer clic, la aplicación redirige
silenciosamente a Inicio, sin ningún toast ni mensaje — el rol
Administrador no tiene el permiso `sucursales:crear`. El frontend debería
ocultar por completo la acción cuando el usuario no tiene el permiso
correspondiente, en vez de mostrarla y bloquearla después sin explicación.
Captura: [`09-admin-boton-nueva-sucursal-visible-sin-permiso.jpg`](capturas_e2e_puebla/09-admin-boton-nueva-sucursal-visible-sin-permiso.jpg).

Como contraste positivo: la página `/roles` es visible (solo lectura, sin
iconos de editar/eliminar) para el Administrador — muestra el catálogo
completo de roles y conteo de permisos pero no permite modificarlos; esto
parece intencional y no se marca como bug.

---

## Hallazgos de producto señalados por el usuario

Durante la revisión de "Extras" y "Tipos de Evento" en la sucursal nueva, se
observó que catálogos creados en sesiones anteriores para **otras**
franquicias ("Zamora Plaza", etc.) seguían apareciendo con alcance
"Global", visibles y seleccionables para "Puebla Angelópolis" (p.ej. "Renta
de Trampolín" con descripción "disponible en el área exterior... en Zamora
Plaza"). El usuario intervino explícitamente durante la sesión:

> "documenta eso de quitar alcance global, todo debe ser solo por sucursal"
> "nada global, nada"

**Esto es una decisión de producto explícita, no una sugerencia**: se debe
**eliminar por completo el concepto de alcance "Global"** de todos los
catálogos que hoy lo soportan (`extras`, `tipos_evento`, y los 5
`metodos_pago` semilla que quedaron marcados como globales antes del fix
`7e64469`). Cada sucursal/franquicia debe operar con sus propios catálogos
de forma exclusiva, sin ningún dato ni configuración compartida entre
franquicias distintas.

**Alcance del trabajo pendiente:**
1. **Backend:** quitar el campo `sucursal_id: NULL` como opción válida en
   `ExtrasCrear`/`TiposEventoCreate` (o equivalente); decidir qué hacer con
   los registros ya existentes con `sucursal_id = NULL` — lo más seguro es
   asignarlos a la sucursal donde se crearon originalmente (recuperable por
   `creado_por` + la sucursal de ese usuario en el momento de creación, si
   quedó registro) en vez de borrarlos, y confirmar con el equipo antes de
   ejecutar esa migración de datos porque afecta reservaciones/eventos ya
   existentes que los referencian.
2. **Backend:** revisar y quitar cualquier lógica de fallback tipo
   "si `sucursal_id` es NULL, mostrar a todos" en los listados de `extras`,
   `tipos_evento` y `metodos_pago`.
3. **Frontend:** quitar el checkbox "Disponible en todas las sucursales
   (global)" de los modales "Nuevo Extra" y "Nuevo Tipo de Evento"; quitar
   la columna "Alcance" de esas tablas si ya no aplica (o dejarla si sigue
   habiendo datos legados por depurar).
4. **Métodos de Pago:** el modal de creación ya no ofrece la opción global
   (fix `7e64469`), pero los 5 métodos semilla (`Transferencia`, `Prueba
   Efectivo`, `Tarjeta de Credito`, `Tarjeta`, `Efectivo`) siguen con
   `sucursal_id = NULL` — hace falta la misma limpieza de datos.
5. Confirmar con el usuario/equipo el criterio para asignar sucursal a los
   registros legados antes de tocar producción.

---

## Plan de ejecución del flujo completo de la app

Flujo recomendado, de punta a punta, para dar de alta y operar una
franquicia nueva — útil como checklist de onboarding y como guion de
regresión manual/QA en cada release:

### 1. Alta de franquicia (rol AdministradorSistema)
1. Login con cuenta de sysadmin.
2. Crear la sucursal (`Sucursales → Nueva Sucursal`) — **usar un teléfono
   sin espacios (máx. 15 caracteres) hasta que se corrija BUG-P01**.
3. Crear el usuario Administrador de la sucursal (`Usuarios → Registrar
   usuario`, rol Administrador, sin sucursal) o usar el atajo
   "+ Crear Administrador" desde el formulario de la sucursal.
4. Asignar el administrador a la sucursal (editar la sucursal → buscador de
   "Administrador Responsable").
5. Verificar login del nuevo administrador y que el selector de sucursal
   (si tiene más de una) funcione.

### 2. Alta de personal (rol Administrador)
6. Crear un usuario por cada rol operativo necesario: Cajero, Cocina,
   Personal de atención de niños (y otro Administrador si aplica
   multi-sucursal).
7. Verificar login de cada uno y que el menú lateral solo muestre lo que su
   rol permite — **si se usa el rol "Personal de atención de niños" con la
   configuración semilla actual, corregir primero BUG-P06 o el check-in
   quedará bloqueado.**

### 3. Catálogo base (rol Administrador)
8. Proveedores.
9. Insumos (con unidad base/compra correctas) y sus presentaciones de
   compra si aplica.
10. Productos (con receta por insumo) — **usar nombres únicos globalmente
    hasta que se corrija BUG-P02**, ya que el nombre no puede repetirse
    entre sucursales.
11. Combos (mínimo 2 productos).
12. Paquetes de evento.
13. Extras, Tipos de Evento, Métodos de Pago — **por ahora seguirán
    apareciendo también los "Global" de otras franquicias hasta que se
    resuelva el hallazgo de producto de la sección anterior.**
14. Configuración de Puntos de Lealtad (% de retorno, caducidad, valor del
    punto, activar programa).

### 4. Ciclo de compra e inventario
15. Registrar una compra a proveedor con una o más líneas.
16. Recibirla y confirmar que el stock e historial de Kardex se actualicen.

### 5. Ciclo de eventos/reservaciones
17. Crear una reservación (datos del cliente, evento, paquete/extras).
18. Registrar el anticipo con "Pago Multimodal" — **en ventanas de navegador
    de menos de ~800px de alto, agrandar la ventana o hacer zoom-out hasta
    que se corrija BUG-P03, o el botón "Aplicar Pago" quedará inalcanzable.**
19. Confirmar la reservación.

### 6. Ciclo de check-in / estancia
20. Registrar pulseras nuevas (`Registro de Pulseras`).
21. Hacer el check-in del niño (`Control de Acceso → Nuevo Registro`):
    datos del tutor, datos del niño, fotos de INE/llegada, vincular
    pulsera(s) — **actualmente bloqueado por BUG-P04 si no hay cámara
    disponible o si falta identificar qué campo exacto exige el botón
    "Completar Pago".**
22. Vincular la(s) pulsera(s) del niño (paso "2. Pulseras" del wizard).
23. Confirmar el registro (paso "3. Listo").
24. Verificar en `Control de Acceso` que el niño aparece como activo.

### 7. Ciclo de POS (Caja/Cocina)
25. Abrir turno de Caja si aplica.
26. Crear un pedido, mezclando productos sueltos y combos.
27. Cobrar con "Pago Multimodal" (capturar celular para lealtad si aplica).
28. Verificar en Cocina el avance Pendiente → En Preparación → Listo →
    Entregado.
29. **Verificar en Insumos/Kardex que el stock se haya descontado según la
    receta — actualmente no ocurre, ver BUG-P03.**

### 8. Checkout y cierre
30. Checkout de la estancia del niño (cobro de cargos extra si aplica) —
    no se pudo completar en esta sesión por el bloqueo de BUG-P04.
31. Verificar el Kardex de puntos de lealtad del cliente — **confirmar que
    tanto el anticipo de la reservación como cualquier pago en caja otorguen
    puntos de forma consistente, ver BUG-P05.**
32. Revisar Reportes (Dashboard, Reporte de Stock, Reporte de Lealtad) y
    confirmar que reflejan la actividad de la sucursal correctamente.

### 9. Verificación de permisos (regresión recomendada en cada release)
33. Repetir el login de cada rol no-administrador y confirmar que el menú y
    el acceso directo por URL a rutas ajenas siguen bloqueados.
34. Confirmar que ningún botón de acción visible lleve a un permiso que el
    rol no tiene sin explicar por qué (ver BUG-P07).

---

## Qué falta por implementar / gaps

Además de los bugs puntuales de arriba, esta sesión deja identificados los
siguientes vacíos de producto/ingeniería, en orden aproximado de impacto:

1. **Eliminar el alcance "Global" de extras/tipos de evento/métodos de
   pago** (decisión de producto ya tomada por el usuario, ver sección
   dedicada arriba) — es el gap de mayor alcance detectado en esta sesión.
2. **Descuento de inventario por venta roto de nuevo** (BUG-P03) — need
   auditar `inventario_service.descontar_por_venta` (o el hook que lo
   dispara desde `comandas`) porque en la sesión anterior sí funcionaba vía
   API directa; algo entre el fix del carrito (`91317bb`) y el flujo real
   de UI dejó de dispararlo, o nunca se disparó desde el flujo de "marcar
   entregado" y solo se probó por API en su momento.
3. **Restricción `UNIQUE` global en `productos.nombre`** (BUG-P02) —
   bloqueante estructural para cualquier catálogo compartido de nombres
   comunes entre franquicias; requiere migración a `UNIQUE(sucursal_id,
   nombre)`.
4. **Normalización de teléfonos inconsistente entre formularios** — el
   patrón correcto (normalizar a solo dígitos antes de persistir, como en
   `reservaciones`) no se aplicó a `sucursales`; recomendado auditar todos
   los `INSERT`/`UPDATE` que escriban en columnas de teléfono para aplicar
   el mismo criterio, y de paso resolver el drift de esquema real
   (`CHAR` vs `VARCHAR`) en las 3 columnas afectadas
   (`sucursales.telefono`, `reservaciones.telefono_cliente`,
   `tutores.telefono`).
5. **Permisos semilla del rol "Personal de atención de niños" incompletos**
   (BUG-P06) — o se corrige el seed/rol en la BD real, o se documenta que
   es responsabilidad de cada implementación ajustar permisos por rol antes
   de operar (pero en ese caso el rol debería crearse sin permisos por
   defecto en vez de con permisos que no coinciden con su descripción).
6. **Botones de acción sin ocultar según permisos** (BUG-P07, y
   parcialmente BUG-P04) — patrón a nivel de frontend: validar permisos
   antes de renderizar acciones, no solo antes de ejecutar el submit.
7. **Feedback de validación inconsistente entre formularios** (UX-P01) —
   "Nueva Sucursal" no valida visualmente; "Registrar usuario" sí. Vale la
   pena una pasada de consistencia en todos los formularios de alta.
8. **Responsividad de tarjetas (Extras) y de modales (Pago Multimodal)** en
   viewports comunes de escritorio/laptop (UX-P02, UX-P03) — ningún caso
   fue probado en móvil/tablet en esta sesión; dado que ya hay problemas en
   desktop estándar, es razonable asumir que en pantallas más pequeñas el
   problema es peor. Recomendado agregar pruebas de responsividad al ciclo
   de QA.
9. **No se pudo verificar en esta sesión** (por el bloqueo de BUG-P04):
   checkout de estancia, cobro de cargo extra al checkout, y el reporte de
   una estancia cerrada con sus puntos de lealtad asociados. Queda
   pendiente para la próxima sesión una vez resuelto el bloqueo del
   check-in.
10. **Cobertura de pruebas automatizadas:** como ya se documentó en
    memoria del proyecto, el backend no tiene tests unitarios reales
    (`tests/` solo con `__init__.py`). Varios de los bugs de esta sesión
    (restricción `UNIQUE` global, columnas `CHAR` vs `VARCHAR`, botón
    deshabilitado sin manejo de UI) son exactamente el tipo de regresión
    que una suite de pruebas de integración (backend) y de componente
    (frontend) detectaría antes de llegar a control de calidad manual.

---

## Datos creados

Todo quedó **activo en la BD real compartida**, según el patrón ya usado en
la sesión anterior.

**Sucursal**
- Puebla Angelópolis — clave `SUC-PUE-01`, id `5941b6bf-2515-4754-a60b-dbc79192768e`

**Usuarios** (contraseña `12345678` en todos)
- Ana Regina Ortíz Vela — `ana.ortiz@woowkids.dev` — Administrador (Puebla Angelópolis)
- Marisol Guadalupe Rangel — `cajero.puebla@woowkids.dev` — Cajero
- Braulio César Herrera Nava — `cocina.puebla@woowkids.dev` — Cocina
- Yolanda Ibarra Cruz — `atencion.puebla@woowkids.dev` — Personal de atención de niños (rol sin permisos suficientes, ver BUG-P06)

**Catálogo**
- Proveedor: Distribuidora Angelópolis Alimentos
- Insumos: Harina de trigo (presentación "Costal 20kg"), Queso Mozzarella
- Productos: Pizza Individual Angelópolis (con receta), Refresco Individual Angelópolis, Combo Pizza y Refresco Angelópolis
- Paquete: Paquete Fiesta Angelópolis
- Extra propio: Renta de Trampolín Angelópolis
- Tipo de evento propio: Festival Angelópolis
- Método de pago propio: Efectivo Angelópolis
- Configuración de lealtad: 5% retorno, 30 días caducidad, $1/punto
- Pulseras: `PUE-00001`, `PUE-00002`, `PUE-00003` (activas, ninguna vinculada a un niño por el bloqueo de BUG-P04)

**Movimientos/transacciones**
- Compra recibida: Distribuidora Angelópolis Alimentos, $1,400.00
- Reservación: "Cumpleaños Infantil — Laura Ximena Torres", 15 ago 2026, `Confirmada`, anticipo $1,068.00 pagado (sin puntos de lealtad otorgados, BUG-P05)
- Check-in de "Emilia Torres": datos y foto-placeholders capturados, **sin completar** por BUG-P04 — sin pulseras vinculadas, sin estancia generada
- Comanda `TICK-9917`: Pizza Individual ×2 (1 suelta + 1 en combo) + Combo Pizza y Refresco ×1 + Refresco Individual ×2 (1 suelto + 1 en combo), $230.00, efectivo, entregada — **sin descuento de inventario** (BUG-P03); otorgó 12 puntos de lealtad a Laura (celular `2229876543`)
