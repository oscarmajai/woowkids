#!/bin/sh
# Comando `respaldos` dentro de los contenedores (ver scripts/respaldos.py).
# Con `docker exec` se entra como root: los respaldos se escriben como el
# usuario de la app para que el proceso programado pueda seguir usándolos.
# Solo `restaurar` sigue como root, porque detiene el backend con supervisorctl.
cd /app || exit 1
if [ "$(id -u)" = 0 ] && id woowkids >/dev/null 2>&1 && [ "${1:-}" != restaurar ]; then
    exec runuser -u woowkids -- python scripts/respaldos.py "$@"
fi
exec python scripts/respaldos.py "$@"
