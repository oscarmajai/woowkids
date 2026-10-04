#!/usr/bin/env bash
# Calcula la siguiente versión semántica a partir de los Conventional Commits
# desde el último tag vX.Y.Z:
#   - "tipo!:" o "BREAKING CHANGE" en el cuerpo  -> mayor
#   - "feat:"                                     -> menor
#   - cualquier otro commit                       -> parche
# Sin tags previos la primera versión es v1.0.0, sea cual sea el tipo de los
# commits. Si no hay commits nuevos desde el último tag no imprime nada (no hay
# nada que liberar).
set -euo pipefail

ultimo=$(git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null || echo "")
if [ -n "$ultimo" ]; then
    rango="$ultimo..HEAD"
    base="${ultimo#v}"
else
    echo "v1.0.0"
    exit 0
fi

commits=$(git log --no-merges --format='%s%n%b%n--fin--' "$rango")
[ -z "$(git log --no-merges --format='%H' "$rango")" ] && exit 0

IFS=. read -r mayor menor parche <<<"$base"

if grep -qE '^[a-z]+(\([^)]*\))?!:|BREAKING CHANGE' <<<"$commits"; then
    mayor=$((mayor + 1)); menor=0; parche=0
elif grep -qE '^feat(\([^)]*\))?:' <<<"$commits"; then
    menor=$((menor + 1)); parche=0
else
    parche=$((parche + 1))
fi

echo "v$mayor.$menor.$parche"
