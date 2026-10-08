import { describe, expect, it } from 'vitest'

import {
  avisoLiquidacion,
  fechaLimiteLiquidacionTexto,
  calcularPulseras,
  cantidadExtra,
  dentroDePlazo,
  detallePulseras,
  diasParaEvento,
  exigeLiquidacionAlReservar,
  faltanPulserasHoy,
  fechaLimiteLiquidacion,
  montoPorPorcentaje,
  porcentajeAnticipoMinimo,
  recalcularReservacion,
  resumenPorCobrar,
  sumarHoras,
  totalExtras,
} from './reservacionPrecio'
import type { Reservaciones } from '@/types/reservaciones'

const RESERVACION = {
  id: 'r1',
  sucursal_id: 's1',
  tipo_evento_id: 't1',
  paquete_id: 'p1',
  nombre_cliente: 'Ana',
  apellidos_cliente: null,
  telefono_cliente: '3310000000',
  email_cliente: null,
  nombre_festejado: null,
  edad_festejado: null,
  fecha_evento: '2027-02-25',
  hora_inicio: '15:00:00',
  hora_fin: '18:00:00',
  numero_personas: 10,
  precio_base: '5000',
  precio_personas_extra: '1500', // 50/hora × 10 invitados × 3 horas
  horas_reservadas: 3,
  precio_horas: '0',
  precio_productos: '200',
  precio_extras: '0',
  descuento: '0',
  precio_total: '6700',
  anticipo: '2010',
  monto_pagado: '2010',
  saldo_pendiente: '4690',
  estado: 'confirmada',
  comanda_enviada: false,
  notas: null,
  activo: true,
  creado: '2026-08-01T00:00:00Z',
  creado_por: null,
  modificado: null,
  modificado_por: null,
} as unknown as Reservaciones

describe('calcularPulseras', () => {
  it('multiplica tarifa por invitados y por horas', () => {
    expect(calcularPulseras(50, 10, 3)).toBe(1500)
  })

  it('cobra al menos una hora aunque llegue cero', () => {
    // Un horario mal capturado no debe anular el cargo de pulseras.
    expect(calcularPulseras(50, 10, 0)).toBe(500)
  })
})

describe('recalcularReservacion', () => {
  it('reconstruye el total al subir el número de invitados', () => {
    const r = recalcularReservacion(RESERVACION, 50, { invitados: 20 })
    // 5000 base + (50 × 20 × 3) pulseras + 200 productos = 8200
    expect(r.precio_personas_extra).toBe('3000')
    expect(r.precio_total).toBe('8200')
    expect(r.anticipoExcede).toBe(false)
  })

  it('reconstruye el total al agregar horas', () => {
    const r = recalcularReservacion(RESERVACION, 50, { horas: 5 })
    // 5000 + (50 × 10 × 5) + 200 = 7700
    expect(r.horas_reservadas).toBe(5)
    expect(r.precio_total).toBe('7700')
  })

  it('avisa cuando el total nuevo quedaría por debajo de lo ya pagado', () => {
    // Con un anticipo de 2010, bajar a 1 invitado deja el total en 5250...
    expect(recalcularReservacion(RESERVACION, 50, { invitados: 1 }).anticipoExcede).toBe(false)
    // ...pero con un evento casi liquidado el servidor rechaza la edición.
    const casiLiquidada = { ...RESERVACION, monto_pagado: '6600' } as Reservaciones
    expect(recalcularReservacion(casiLiquidada, 50, { invitados: 1 }).anticipoExcede).toBe(true)
  })

  it('compara contra todo lo pagado, no solo contra el anticipo', () => {
    // Anticipo de 2010 + abonos: ya se pagaron 6600 aunque `anticipo` no cambie.
    const conAbonos = { ...RESERVACION, anticipo: '2010', monto_pagado: '6600' } as Reservaciones
    expect(recalcularReservacion(conAbonos, 50, { invitados: 1 }).anticipoExcede).toBe(true)
  })

  it('reevalúa las pulseras con la tarifa vigente del paquete', () => {
    // La fórmula es tarifa × invitados × horas sobre el total, no un
    // incremental: si el paquete cambió de tarifa, el evento se recalcula
    // completo a la tarifa de hoy.
    const r = recalcularReservacion(RESERVACION, 125, { horas: 4 })
    expect(r.precio_personas_extra).toBe('5000') // 125 × 10 × 4
    expect(r.precio_total).toBe('10200') // 5000 + 5000 + 200
  })

  it('trata como una hora las reservaciones antiguas con 0 horas', () => {
    const legado = { ...RESERVACION, horas_reservadas: 0 } as Reservaciones
    expect(recalcularReservacion(legado, 50, {}).precio_personas_extra).toBe('500')
  })

  it('no arrastra el total anterior: lo reconstruye desde las partes', () => {
    // Volver al valor original tras varios cambios debe dar exactamente el total
    // original, sin desviaciones acumuladas.
    const subida = recalcularReservacion(RESERVACION, 50, { invitados: 40 })
    expect(subida.precio_total).toBe('11200')
    const regreso = recalcularReservacion(RESERVACION, 50, { invitados: 10 })
    expect(regreso.precio_total).toBe(RESERVACION.precio_total)
  })

  it('recalcula los extras por persona y por hora, igual que el servidor', () => {
    const conExtras = {
      ...RESERVACION,
      precio_extras: '1850', // 10 × 35 + 3 × 350 + 450
      precio_total: '8550',
    } as Reservaciones
    const extras = [
      { unidad: 'persona', precio_unitario: '35', cantidad: 10 },
      { unidad: 'hora', precio_unitario: '350', cantidad: 3 },
      { unidad: 'evento', precio_unitario: '450', cantidad: 1 },
    ]
    const r = recalcularReservacion(conExtras, 50, { invitados: 15, horas: 4 }, extras)
    // extras: 15 × 35 + 4 × 350 + 450 = 2375; pulseras 50 × 15 × 4 = 3000
    expect(r.precio_extras).toBe('2375')
    expect(r.precio_total).toBe(String(5000 + 3000 + 200 + 2375))
  })

  it('sin extras guardados conserva el precio_extras de la reservación', () => {
    const legado = { ...RESERVACION, precio_extras: '485' } as Reservaciones
    expect(recalcularReservacion(legado, 50, { invitados: 20 }).precio_extras).toBe('485')
  })
})

describe('faltanPulserasHoy (UX Nueva reservación)', () => {
  it('avisa solo si el evento es hoy y no alcanzan las libres', () => {
    expect(faltanPulserasHoy(14, 20, 0)).toBe(true)
    expect(faltanPulserasHoy(14, 12, 0)).toBe(false)
  })

  it('no compara las libres de hoy contra un evento futuro', () => {
    // Caso: "La sucursal tiene 14 pulseras y el evento pide 20" para un evento en 3 semanas.
    expect(faltanPulserasHoy(14, 20, 21)).toBe(false)
  })

  it('sin fecha o sin inventario consultado no avisa', () => {
    expect(faltanPulserasHoy(14, 20, null)).toBe(false)
    expect(faltanPulserasHoy(null, 20, 0)).toBe(false)
  })
})

describe('resumenPorCobrar', () => {
  it('no suma las reservaciones canceladas aunque tengan pagos y saldo', () => {
    const r = [
      { id: 'a', estado: 'confirmada', saldo_pendiente: '5330.00' },
      { id: 'a', estado: 'confirmada', saldo_pendiente: '5330.00' }, // segundo pago
      { id: 'b', estado: 'cancelada', saldo_pendiente: '1.00' },
      { id: 'c', estado: 'completada', saldo_pendiente: '0.00' },
      { id: 'd', estado: 'pendiente', saldo_pendiente: '-40.00' }, // sobrepago
    ] as Reservaciones[]
    expect(resumenPorCobrar(r)).toEqual({ eventos: 1, total: 5330 })
  })
})

describe('detallePulseras', () => {
  it('desglosa el cargo guardado en precio_personas_extra como pulseras', () => {
    // R-0008: "Personas extra $2,520" era 12 pulseras × 3 h × $70.
    const r = { numero_personas: 12, horas_reservadas: 3, precio_personas_extra: '2520.00' }
    expect(detallePulseras(r, 3)).toEqual({ invitados: 12, horas: 3, tarifa: 70 })
  })

  it('usa las horas del horario si la reservación no las guardó', () => {
    const r = { numero_personas: 10, horas_reservadas: 0, precio_personas_extra: '2000' }
    expect(detallePulseras(r, 4)).toEqual({ invitados: 10, horas: 4, tarifa: 50 })
  })
})

describe('cantidadExtra', () => {
  it('por persona = invitados, por hora = horas, por evento = 1', () => {
    expect(cantidadExtra('persona', 12, 3)).toBe(12)
    expect(cantidadExtra('hora', 12, 3)).toBe(3)
    expect(cantidadExtra('evento', 12, 3)).toBe(1)
    expect(cantidadExtra(undefined, 12, 3)).toBe(1)
  })

  it('la bolsita de $35 por persona para 12 niños suma $420, no $35', () => {
    const extras = [{ unidad: 'persona', precio_unitario: '35', cantidad: 1 }]
    expect(totalExtras(extras, 12, 3)).toBe(420)
  })
})

describe('sumarHoras', () => {
  it('suma horas al horario de fin', () => {
    expect(sumarHoras('18:00:00', 2)).toBe('20:00:00')
  })

  it('se topa antes de medianoche en vez de pasar al día siguiente', () => {
    // La reservación guarda una sola fecha y exige hora_fin > hora_inicio;
    // cruzar la medianoche rompería esa restricción.
    expect(sumarHoras('22:00:00', 5)).toBe('23:59:00')
  })
})

describe('plazo de liquidación', () => {
  it('la fecha límite es una semana antes del evento', () => {
    expect(fechaLimiteLiquidacion('2027-02-25').toISOString().slice(0, 10)).toBe('2027-02-18')
  })

  it('el aviso del comprobante nombra la fecha límite y la cancelación', () => {
    const fecha = fechaLimiteLiquidacionTexto('2027-02-25')
    expect(fecha).toContain('18')
    expect(fecha).toContain('2027')
    expect(avisoLiquidacion(fecha)).toBe(
      `Liquida el saldo a más tardar el ${fecha}; si no, la reservación se cancela.`,
    )
  })

  it('permite editar mientras falte más de una semana', () => {
    expect(dentroDePlazo('2027-02-25', new Date(2027, 1, 17))).toBe(true)
  })

  it('bloquea el mismo día del límite y después', () => {
    expect(dentroDePlazo('2027-02-25', new Date(2027, 1, 18))).toBe(false)
    expect(dentroDePlazo('2027-02-25', new Date(2027, 1, 24))).toBe(false)
  })
})

describe('reglas de anticipo (iguales a las del servidor)', () => {
  it('el mínimo es 30 % o el del paquete si es mayor', () => {
    expect(porcentajeAnticipoMinimo(null)).toBe(30)
    expect(porcentajeAnticipoMinimo('40.00')).toBe(40)
    expect(porcentajeAnticipoMinimo('20.00')).toBe(30)
  })

  it('redondea a pesos con mitades hacia arriba, sin ruido de flotante', () => {
    // R-0008: 30 % de 7615 = 2284.5 -> 2285, como el servidor.
    expect(montoPorPorcentaje(7615, 30)).toBe(2285)
    expect(montoPorPorcentaje(13815, 40)).toBe(5526)
    expect(montoPorPorcentaje(1234.5, 50)).toBe(617)
  })

  it('cuenta los días al evento en fecha local', () => {
    const hoy = new Date(2026, 9, 3, 23, 30)
    expect(diasParaEvento('2026-10-03', hoy)).toBe(0)
    expect(diasParaEvento('2026-10-10', hoy)).toBe(7)
    expect(diasParaEvento('2026-10-11', hoy)).toBe(8)
  })

  it('a 7 días o menos se liquida al reservar', () => {
    expect(exigeLiquidacionAlReservar(0)).toBe(true)
    expect(exigeLiquidacionAlReservar(7)).toBe(true)
    expect(exigeLiquidacionAlReservar(8)).toBe(false)
  })
})
