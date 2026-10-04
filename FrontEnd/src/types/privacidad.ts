/** GET /api/privacidad/aviso — versión vigente con los datos del responsable ya puestos. */
export interface AvisoPrivacidad {
  version: number
  vigenteDesde: string
  /** Fecha (AAAA-MM-DD) en que entró en vigor, hora del centro del país. */
  fechaVigencia: string
  nombreComercial: string
  textoIntegral: string
  textoSimplificado: string
}

/** Datos del responsable que llenan los marcadores {{...}} del aviso. */
export interface ResponsableAviso {
  razonSocial: string
  nombreComercial: string
  domicilio: string
  areaDatosPersonales: string
  correoDatosPersonales: string
  telefonoDatosPersonales: string
  urlAviso: string
  diasConservacionImagenes: number
  aniosConservacionRegistros: number
}

export interface VersionAviso {
  version: number
  vigenteDesde: string
  publicadoPor: string | null
  motivoCambio: string | null
}

/** GET /api/privacidad/admin/aviso — solo AdministradorSistema. */
export interface AvisoPrivacidadAdmin {
  version: number
  vigenteDesde: string
  publicadoPor: string | null
  motivoCambio: string | null
  responsable: ResponsableAviso
  /** Plantillas, con sus marcadores {{...}} sin reemplazar. */
  textoIntegral: string
  textoSimplificado: string
  /** Marcador → qué dato lo llena. */
  marcadores: Record<string, string>
  /** Datos del responsable sin capturar. */
  pendientes: string[]
  historial: VersionAviso[]
}

/** POST /api/privacidad/admin/aviso. Sin textos, se conservan los vigentes. */
export interface PublicarAvisoPayload {
  versionBase: number
  responsable: ResponsableAviso
  textoIntegral?: string
  textoSimplificado?: string
  motivoCambio?: string
}

/** Bloques del texto del aviso ("# " título, "## " sección, "- " viñeta). */
export type BloqueAviso =
  { tipo: 'titulo' | 'seccion' | 'parrafo'; texto: string } | { tipo: 'lista'; items: string[] }
