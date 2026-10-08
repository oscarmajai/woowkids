#!/usr/bin/env bash
# Prueba el control de migraciones de docker/entrypoint.sh contra un PostgreSQL
# real, con la imagen del backend ya construida:
#
#   1. BD vacía: se crea con el maestro y todas las migraciones quedan registradas.
#   2. Segundo arranque: no se aplica nada.
#   3. BD de una instalación anterior al control de migraciones: se registra la
#      base y se aplica lo posterior (074 restaura el permiso de cobro).
#   4. Migración nueva: se aplica una sola vez.
#   5. Migración que falla: el arranque termina con error y no se registra.
#
# Uso:  ./scripts/probar_control_migraciones.sh <imagen-del-backend>
# Requiere: docker.
set -euo pipefail

IMAGEN="${1:?Uso: $0 <imagen-del-backend>}"
RED="wk-migr-$$"
PG="wk-migr-pg-$$"
URL="postgresql://dev:dev@$PG:5432/woowkids"
TMP="$(mktemp -d)"

limpiar() {
    docker rm -f "$PG" >/dev/null 2>&1 || true
    docker network rm "$RED" >/dev/null 2>&1 || true
    rm -rf "$TMP"
}
trap limpiar EXIT

falla() { echo "FALLA: $*" >&2; exit 1; }
sql() { docker exec "$PG" psql -U dev -d woowkids -v ON_ERROR_STOP=1 -tAc "$1"; }

# Corre el entrypoint completo con `true` como comando; los argumentos extra
# van a `docker run` (p. ej. un -v con una migración adicional).
arrancar() {
    docker run --rm --network "$RED" -e DATABASE_URL="$URL" \
        -e SECRET_KEY=prueba -e MINIO_ACCESS_KEY=prueba -e MINIO_SECRET_KEY=prueba \
        "$@" "$IMAGEN" true
}

docker network create "$RED" >/dev/null
docker run -d --name "$PG" --network "$RED" \
    -e POSTGRES_USER=dev -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=woowkids \
    postgres:16-alpine >/dev/null
until sql 'SELECT 1' >/dev/null 2>&1; do sleep 1; done

total=$(docker run --rm --entrypoint sh "$IMAGEN" -c 'ls sql/migrations | grep -c "\.sql$"')

echo "==> 1. BD vacía"
arrancar >"$TMP/1.log" 2>&1 || { cat "$TMP/1.log"; falla "el primer arranque terminó con error"; }
[ "$(sql 'SELECT count(*) FROM schema_migraciones')" = "$total" ] ||
    falla "se esperaban $total migraciones registradas"
grep -q "pendientes aplicadas: 0" "$TMP/1.log" || falla "una BD nueva no debe aplicar migraciones"

echo "==> 2. Segundo arranque"
arrancar >"$TMP/2.log" 2>&1 || { cat "$TMP/2.log"; falla "el segundo arranque terminó con error"; }
grep -q "pendientes aplicadas: 0" "$TMP/2.log" || falla "el segundo arranque aplicó migraciones"

echo "==> 3. BD de una versión sin control de migraciones"
sql "DROP TABLE schema_migraciones" >/dev/null
sql "DELETE FROM rol_permisos WHERE permiso_id = (SELECT id FROM permisos WHERE codigo = 'restaurante:registrar_pago');
     DELETE FROM permisos WHERE codigo = 'restaurante:registrar_pago'" >/dev/null
arrancar >"$TMP/3.log" 2>&1 || { cat "$TMP/3.log"; falla "el arranque sobre una BD sin control terminó con error"; }
[ "$(sql "SELECT count(*) FROM permisos WHERE codigo = 'restaurante:registrar_pago'")" = "1" ] ||
    falla "no se aplicó 074 sobre la BD sin control"
[ "$(sql 'SELECT count(*) FROM schema_migraciones')" = "$total" ] ||
    falla "tras registrar la base y aplicar lo posterior deben quedar $total registradas"

echo "==> 4. Migración nueva"
printf 'CREATE TABLE prueba_control_migraciones (id int);\n' >"$TMP/999_prueba.sql"
nueva=(-v "$TMP/999_prueba.sql:/app/sql/migrations/999_prueba.sql:ro")
arrancar "${nueva[@]}" >"$TMP/4.log" 2>&1 || { cat "$TMP/4.log"; falla "no se aplicó la migración nueva"; }
grep -q "Aplicando migración 999_prueba.sql" "$TMP/4.log" || falla "no se reportó la migración nueva"
# No es idempotente: si se aplicara dos veces, el CREATE TABLE fallaría.
arrancar "${nueva[@]}" >"$TMP/4b.log" 2>&1 || { cat "$TMP/4b.log"; falla "la migración nueva se volvió a aplicar"; }

echo "==> 5. Migración que falla"
printf 'CREATE TABLE prueba_falla (id int);\nSELECT * FROM tabla_que_no_existe;\n' >"$TMP/999_zz_falla.sql"
if arrancar "${nueva[@]}" -v "$TMP/999_zz_falla.sql:/app/sql/migrations/999_zz_falla.sql:ro" \
    >"$TMP/5.log" 2>&1; then
    falla "el arranque debió terminar con error"
fi
grep -q "falló la migración 999_zz_falla.sql" "$TMP/5.log" || falla "no se reportó la migración fallida"
[ "$(sql "SELECT count(*) FROM schema_migraciones WHERE archivo = '999_zz_falla.sql'")" = "0" ] ||
    falla "la migración fallida quedó registrada"
[ "$(sql "SELECT to_regclass('public.prueba_falla') IS NULL")" = "t" ] ||
    falla "la migración fallida quedó aplicada a medias"

echo "OK: control de migraciones"
