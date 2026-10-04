from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.textos import Nombre100


class TiposEventoBase(BaseModel):
    nombre: Nombre100
    descripcion: str | None = None


class TiposEventoCreate(TiposEventoBase):
    # Solo relevante para AdministradorSistema (sin sucursal propia); para
    # cualquier otro rol el router ignora este valor y usa siempre la
    # sucursal del usuario autenticado. Ya no existe el concepto de tipo de
    # evento "global" (sucursal_id NULL).
    sucursal_id: UUID | None = None


class TiposEventoUpdate(BaseModel):
    nombre: Nombre100 | None = None
    descripcion: str | None = None
    activo: bool | None = None


class TiposEventoOut(TiposEventoBase):
    id: UUID
    sucursal_id: UUID | None
    activo: bool
    creado: datetime
    creado_por: UUID | None
    modificado: datetime | None
    modificado_por: UUID | None
    # Solo lo puebla el listado; en crear/actualizar/obtener queda en 0.
    paquetes_count: int = 0

    model_config = {"from_attributes": True}
