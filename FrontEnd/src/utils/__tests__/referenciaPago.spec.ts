import { describe, expect, it } from 'vitest'

import { referenciaDePago } from '@/utils/pagos'
import type { AppliedPayment } from '@/types/payments'

const pago = (method: string, authCode?: string): AppliedPayment => ({
  id: method,
  method,
  amount: 100,
  timestamp: new Date(),
  authCode,
})

describe('referenciaDePago', () => {
  it('toma el folio capturado en el teclado de cobro', () => {
    expect(referenciaDePago(pago('Tarjeta', ' 4821 '))).toBe('4821')
  })

  it('sin folio no manda referencia (el backend decide si la exige)', () => {
    expect(referenciaDePago(pago('Efectivo'))).toBeUndefined()
    expect(referenciaDePago(pago('Transferencia', '   '))).toBeUndefined()
  })
})
