#!/bin/sh
# HTTPS de la imagen todo en uno: deja en /data/tls lo que nginx necesita.
#
# - Con certificado propio (/data/tls/propio/servidor.crt y servidor.key, o
#   montados en /certs como woowkids.crt y woowkids.key) se usa ese.
# - Si no, se crea UNA vez una CA local (10 años) y con ella el certificado
#   del servidor para los nombres e IPs de WOOWKIDS_DOMINIOS (más localhost).
#   El del servidor se vuelve a emitir si cambian los nombres o le quedan menos
#   de 30 días; la CA no cambia, así que las terminales que ya confían en ella
#   no tienen que hacer nada.
#
# Las terminales confían en la CA instalando /certificado-woowkids.crt (lo
# sirve nginx también por HTTP, ver /instalar-certificado).
set -eu

TLS=/data/tls
mkdir -p "$TLS"
chmod 700 "$TLS"

if [ -s /certs/woowkids.crt ] && [ -s /certs/woowkids.key ]; then
    PROPIO_CRT=/certs/woowkids.crt PROPIO_KEY=/certs/woowkids.key
elif [ -s "$TLS/propio/servidor.crt" ] && [ -s "$TLS/propio/servidor.key" ]; then
    PROPIO_CRT="$TLS/propio/servidor.crt" PROPIO_KEY="$TLS/propio/servidor.key"
else
    PROPIO_CRT="" PROPIO_KEY=""
fi

if [ -n "$PROPIO_CRT" ]; then
    echo "[tls] Usando el certificado propio $PROPIO_CRT"
    cp "$PROPIO_CRT" "$TLS/servidor.crt"
    cp "$PROPIO_KEY" "$TLS/servidor.key"
    chmod 600 "$TLS/servidor.key"
    # Sin CA local que repartir: la página de instalación lo explica.
    rm -f "$TLS/ca-publica.crt"
    exit 0
fi

# Nombres del certificado: WOOWKIDS_DOMINIOS (separados por coma o espacio).
nombres="localhost 127.0.0.1 $(echo "${WOOWKIDS_DOMINIOS:-}" | tr ',' ' ')"
san=""
for n in $nombres; do
    case "$n" in
        *[!0-9.]*) entrada="DNS:$n" ;;  # tiene algo que no es dígito ni punto
        *) entrada="IP:$n" ;;
    esac
    case ",$san," in *",$entrada,"*) continue ;; esac
    san="${san:+$san,}$entrada"
done

if [ ! -s "$TLS/ca.key" ] || [ ! -s "$TLS/ca.crt" ]; then
    echo "[tls] Creando la autoridad certificadora local de esta instalación"
    openssl req -x509 -new -nodes -newkey rsa:3072 -sha256 -days 3650 \
        -keyout "$TLS/ca.key" -out "$TLS/ca.crt" \
        -subj "/O=Woow Kids/CN=Woow Kids CA local $(date +%Y%m%d%H%M)" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
    chmod 600 "$TLS/ca.key"
fi
cp "$TLS/ca.crt" "$TLS/ca-publica.crt"

emitir=no
if [ ! -s "$TLS/servidor.crt" ] || [ ! -s "$TLS/servidor.key" ]; then
    emitir=si
elif [ "$(cat "$TLS/servidor.san" 2>/dev/null)" != "$san" ]; then
    emitir=si
elif ! openssl x509 -checkend 2592000 -noout -in "$TLS/servidor.crt" >/dev/null 2>&1; then
    emitir=si
elif ! openssl verify -CAfile "$TLS/ca.crt" "$TLS/servidor.crt" >/dev/null 2>&1; then
    emitir=si
fi

if [ "$emitir" = si ]; then
    echo "[tls] Emitiendo el certificado del servidor para: $san"
    openssl req -new -nodes -newkey rsa:2048 -sha256 \
        -keyout "$TLS/servidor.key" -out "$TLS/servidor.csr" \
        -subj "/O=Woow Kids/CN=Woow Kids" 2>/dev/null
    printf 'basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=%s\n' \
        "$san" >"$TLS/servidor.ext"
    # 825 días: el máximo que aceptan iOS y macOS para CAs privadas.
    openssl x509 -req -in "$TLS/servidor.csr" -CA "$TLS/ca.crt" -CAkey "$TLS/ca.key" \
        -CAcreateserial -days 825 -sha256 -extfile "$TLS/servidor.ext" \
        -out "$TLS/servidor.crt" 2>/dev/null
    chmod 600 "$TLS/servidor.key"
    printf '%s' "$san" >"$TLS/servidor.san"
    rm -f "$TLS/servidor.csr" "$TLS/servidor.ext"
fi

if [ -z "${WOOWKIDS_DOMINIOS:-}" ]; then
    echo "[tls] AVISO: WOOWKIDS_DOMINIOS está vacía; el certificado solo sirve para localhost." >&2
    echo "[tls]        Pon el nombre o la IP con que las terminales abren el sistema." >&2
fi
