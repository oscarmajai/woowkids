#!/bin/sh
# Arranque del contenedor del backend.
#
# 1. Espera a que PostgreSQL acepte conexiones.
# 2. Si la BD está vacía (no existe public.usuarios), la crea completa con
#    sql/schema_maestro.sql y, si SEED_DEMO=true, carga sql/seed_local.sql.
# 3. Aplica las migraciones de sql/migrations/ que falten, en orden, y registra
#    cada una en public.schema_migraciones (ver aplicar_migraciones abajo).
# 4. Si SECRET_KEY no viene o es la de fábrica, usa la que generó la primera
#    vez y guardó en public.secretos_sistema (o la genera ahí).
# 5. Crea el administrador del sistema inicial si no existe; debe cambiar su
#    contraseña al entrar.
# 6. Ejecuta el comando del contenedor (uvicorn por defecto).
set -eu

: "${DATABASE_URL:?DATABASE_URL es obligatoria}"

echo "[entrypoint] Esperando a PostgreSQL..."
intentos=0
until psql "$DATABASE_URL" -tAc 'SELECT 1' >/dev/null 2>&1; do
    intentos=$((intentos + 1))
    if [ "$intentos" -ge 60 ]; then
        echo "[entrypoint] PostgreSQL no respondió en 60 s" >&2
        exit 1
    fi
    sleep 1
done

# Última migración incluida en todas las versiones publicadas antes de que
# existiera el control de migraciones (v1.0.0). En una BD de esas versiones,
# todo lo que ordena hasta aquí ya está aplicado; lo posterior se aplica (074 en
# adelante deben ser idempotentes, porque v1.0.1+ ya las traía en el maestro).
MIGRACION_BASE="073_administrador_permisos_turno.sql"

psql_q() { psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q "$@"; }

# Orden byte a byte, igual en cualquier locale (hay prefijos repetidos como
# 019_a / 019_b y 037_00_).
migraciones() { ls sql/migrations | grep '\.sql$' | LC_ALL=C sort; }

registrar() {
    psql_q -c "INSERT INTO public.schema_migraciones (archivo) VALUES ('$1') ON CONFLICT DO NOTHING"
}

# Cada migración pendiente corre en UNA transacción junto con su registro: si
# falla, no queda aplicada a medias ni marcada como hecha, y el contenedor no
# arranca (el error queda en los logs). Las migraciones no deben traer su
# propio BEGIN/COMMIT.
# Antes de migrar una BD que ya tenía datos se guarda un respaldo de la base
# (scripts/respaldos.py): si la versión nueva sale mal, se puede volver atrás.
respaldar_antes_de_migrar() {
    pendientes=0
    for archivo in $(migraciones); do
        hecha=$(psql "$DATABASE_URL" -tAc \
            "SELECT 1 FROM public.schema_migraciones WHERE archivo = '$archivo'")
        [ "$hecha" = "1" ] || pendientes=$((pendientes + 1))
    done
    [ "$pendientes" -eq 0 ] && return 0
    echo "[entrypoint] $pendientes migraciones pendientes: respaldando la BD antes de aplicarlas"
    if ! python scripts/respaldos.py respaldar --motivo antes-de-migrar --solo-bd; then
        echo "[entrypoint] AVISO: no se pudo respaldar antes de migrar; se continúa." >&2
    fi
}

aplicar_migraciones() {
    aplicadas=0
    for archivo in $(migraciones); do
        hecha=$(psql "$DATABASE_URL" -tAc \
            "SELECT 1 FROM public.schema_migraciones WHERE archivo = '$archivo'")
        [ "$hecha" = "1" ] && continue
        echo "[entrypoint] Aplicando migración $archivo"
        if ! psql_q --single-transaction -f "sql/migrations/$archivo" \
            -c "INSERT INTO public.schema_migraciones (archivo) VALUES ('$archivo')"; then
            echo "[entrypoint] ERROR: falló la migración $archivo; no se registró." >&2
            exit 1
        fi
        aplicadas=$((aplicadas + 1))
    done
    echo "[entrypoint] Migraciones pendientes aplicadas: $aplicadas"
}

existe=$(psql "$DATABASE_URL" -tAc "SELECT to_regclass('public.usuarios') IS NOT NULL")
con_control=$(psql "$DATABASE_URL" -tAc "SELECT to_regclass('public.schema_migraciones') IS NOT NULL")

psql_q <<'SQL'
CREATE TABLE IF NOT EXISTS public.schema_migraciones (
    archivo     text        PRIMARY KEY,
    aplicada_en timestamptz NOT NULL DEFAULT now()
);
SQL

if [ "$existe" = "f" ]; then
    echo "[entrypoint] BD vacía: aplicando sql/schema_maestro.sql"
    psql_q -f sql/schema_maestro.sql
    # El maestro equivale a todas las migraciones del repo (el CI lo verifica).
    for archivo in $(migraciones); do registrar "$archivo"; done
    if [ "${SEED_DEMO:-false}" = "true" ]; then
        echo "[entrypoint] SEED_DEMO=true: cargando sql/seed_local.sql"
        psql_q -f sql/seed_local.sql
    fi
elif [ "$con_control" = "f" ]; then
    echo "[entrypoint] BD sin control de migraciones: se registran como aplicadas hasta $MIGRACION_BASE"
    for archivo in $(migraciones); do
        # Comparación de cadenas con el mismo orden que migraciones().
        if [ "$(printf '%s\n%s\n' "$archivo" "$MIGRACION_BASE" | LC_ALL=C sort | head -1)" = "$archivo" ]; then
            registrar "$archivo"
        fi
    done
fi

[ "$existe" = "t" ] && respaldar_antes_de_migrar
aplicar_migraciones

# Clave con la que se firman los tokens. Con la de fábrica (pública en el repo)
# cualquiera podría fabricarse un token de administrador, así que si la
# instalación no definió una propia se genera una aleatoria la primera vez y se
# guarda en la BD: sobrevive reinicios, actualizaciones de la imagen y
# restauraciones de respaldo. Cambiarla solo obliga a volver a iniciar sesión.
SECRET_KEY_DE_FABRICA="woowkids-secret-key-cambiar-en-produccion"
if [ -z "${SECRET_KEY:-}" ] || [ "$SECRET_KEY" = "$SECRET_KEY_DE_FABRICA" ]; then
    nueva_clave=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -v valor="$nueva_clave" <<'SQL'
INSERT INTO public.secretos_sistema (nombre, valor)
VALUES ('secret_key', :'valor')
ON CONFLICT (nombre) DO NOTHING;
SQL
    SECRET_KEY=$(psql "$DATABASE_URL" -tAc \
        "SELECT valor FROM public.secretos_sistema WHERE nombre = 'secret_key'")
    export SECRET_KEY
    echo "[entrypoint] SECRET_KEY propia de esta instalación (guardada en la BD)"
fi

# Administrador de sistema inicial para poder entrar a la app. Solo se crea si el
# correo no existe: si después se cambia la contraseña desde la app, no se pisa.
# Al entrar la primera vez, la app le pide cambiar la contraseña.
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@woowkids.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin1234}"
admin_hash=$(ADMIN_PASSWORD="$ADMIN_PASSWORD" python -c \
    "import os; from app.core.security import hash_password; print(hash_password(os.environ['ADMIN_PASSWORD']))")
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q \
    -v email="$ADMIN_EMAIL" -v hash="$admin_hash" <<'SQL'
INSERT INTO public.usuarios (email, password_hash, nombre_completo, rol, debe_cambiar_password)
SELECT :'email', :'hash', 'Administrador', r.id, TRUE
FROM public.roles r
WHERE r.nombre = 'AdministradorSistema'
ON CONFLICT (email) DO NOTHING;
SQL
echo "[entrypoint] Administrador inicial: $ADMIN_EMAIL"

exec "$@"
