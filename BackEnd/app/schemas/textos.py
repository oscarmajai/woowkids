"""Tipos de texto compartidos por los schemas.

Un nombre editable no puede quedar vacío ni en espacios: con `""` el UPDATE se
guardaría y luego la respuesta (que sí exige min_length=1) fallaría con 500,
y el listado de esa sucursal dejaría de cargar.
"""

from typing import Annotated

from pydantic import StringConstraints

Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Nombre100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Nombre150 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
