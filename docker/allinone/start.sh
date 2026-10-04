#!/bin/sh
# Arranque de la imagen todo-en-uno: prepara /data y levanta los 4 procesos.
set -eu

PG_BIN=$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)
export PG_BIN

mkdir -p /data/postgres /data/minio /data/respaldos
chown -R postgres:postgres /data/postgres
chmod 700 /data/postgres
# Respaldos automáticos: en /respaldos si se montó una carpeta del equipo ahí
# (recomendado: así sobreviven a la pérdida del volumen); si no, en /data.
for dir in /data/respaldos /respaldos; do
    [ "$dir" = /respaldos ] && ! grep -qs ' /respaldos ' /proc/mounts && continue
    mkdir -p "$dir/bd" "$dir/archivos"
    chown woowkids "$dir" "$dir/bd" "$dir/archivos" 2>/dev/null || true
done

# Primera vez: inicializa el cluster de PostgreSQL con el usuario y la BD de la app.
if [ ! -s /data/postgres/PG_VERSION ]; then
    echo "[woowkids] Inicializando PostgreSQL en /data/postgres"
    printf '%s' "$POSTGRES_PASSWORD" >/tmp/pgpass
    chown postgres /tmp/pgpass
    su postgres -s /bin/sh -c "$PG_BIN/initdb -D /data/postgres -U '$POSTGRES_USER' \
        --pwfile=/tmp/pgpass --auth=scram-sha-256 --encoding=UTF8 >/dev/null"
    rm -f /tmp/pgpass
    su postgres -s /bin/sh -c "$PG_BIN/pg_ctl -D /data/postgres -o '-c listen_addresses=127.0.0.1' -w start >/dev/null"
    PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres -q \
        -c "CREATE DATABASE \"$POSTGRES_DB\""
    su postgres -s /bin/sh -c "$PG_BIN/pg_ctl -D /data/postgres -m fast -w stop >/dev/null"
fi

# HTTPS: certificado del servidor (y CA local) en /data/tls.
/etc/woowkids/tls.sh

# Puerto 80: redirige a HTTPS (REDIRIGIR_HTTPS=true) o sirve la app como antes.
HTTPS_PUERTO="${HTTPS_PUERTO:-443}"
if [ "${REDIRIGIR_HTTPS:-false}" = "true" ]; then
    sufijo=""
    [ "$HTTPS_PUERTO" != "443" ] && sufijo=":$HTTPS_PUERTO"
    {
        echo "include /etc/nginx/woowkids/certificado.conf;"
        echo "access_log /dev/stdout sin_query_string;"
        echo "location / {"
        echo "    return 301 https://\$host$sufijo\$request_uri;"
        echo "}"
    } >/etc/nginx/woowkids/http.conf
    # Por HTTPS el refresh token puede (y debe) viajar en una cookie Secure.
    export COOKIE_SECURE=true
else
    echo "include /etc/nginx/woowkids/app.conf;" >/etc/nginx/woowkids/http.conf
fi

# Página para instalar el certificado en las terminales, con la huella de la CA.
# /data/tls es solo de root; nginx sirve la copia pública de la CA desde aquí.
huella=""
rm -f /usr/share/woowkids/certificado-woowkids.crt
if [ -s /data/tls/ca-publica.crt ]; then
    install -m 644 /data/tls/ca-publica.crt /usr/share/woowkids/certificado-woowkids.crt
    huella=$(openssl x509 -in /data/tls/ca-publica.crt -noout -fingerprint -sha256 | cut -d= -f2)
fi
sed -e "s/__HUELLA__/$huella/g" -e "s/__PUERTO__/$HTTPS_PUERTO/g" \
    /etc/woowkids/instalar-certificado.html >/usr/share/woowkids/instalar-certificado.html

exec supervisord -c /etc/woowkids/supervisord.conf
