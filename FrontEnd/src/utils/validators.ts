//Solo permite teclear numeros y bloquea todo lo demas en eventos keydown
export function allowOnlyNumbersKeydown(e: KeyboardEvent) {
  const controlKeys = [
    'Backspace',
    'Delete',
    'ArrowUp',
    'ArrowDown',
    'ArrowLeft',
    'ArrowRight',
    'Tab',
    'Enter',
  ]
  if (controlKeys.includes(e.key)) {
    return
  }

  if (e.ctrlKey || e.metaKey) {
    return
  }

  if (!/^[0-9]$/.test(e.key)) {
    e.preventDefault()
  }
}

//Permite solo el uso de letras en eventos keydown
export function allowOnlyLettersKeydown(e: KeyboardEvent) {
  const controlKeys = [
    'Backspace',
    'Delete',
    'ArrowUp',
    'ArrowDown',
    'ArrowLeft',
    'ArrowRight',
    'Tab',
    'Enter',
  ]

  if (controlKeys.includes(e.key) || e.ctrlKey || e.metaKey) {
    return
  }

  const isLetterOrSpace = /^[a-zA-ZáéíóúÁÉÍÓÚüÜñÑ\s]$/.test(e.key)

  if (!isLetterOrSpace) {
    e.preventDefault()
  }
}

/**
 * Regla de la clave de sucursal: obligatoria solo al crear. Hay sucursales
 * anteriores sin clave y editarlas no debe obligar a inventarles una.
 */
export function reglaClaveSucursal(esEdicion: boolean): (v: string | null) => true | string {
  return (v) => esEdicion || !!v?.trim() || 'La clave es requerida'
}
