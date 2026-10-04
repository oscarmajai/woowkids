"""Respaldos automáticos de Woow Kids: base de datos y archivos (MinIO).

Uso (dentro del contenedor, con el comando ``respaldos``):

    respaldos respaldar [--motivo manual] [--solo-bd]   un respaldo ahora
    respaldos programado                                el proceso que corre solo
    respaldos listar                                    respaldos disponibles
    respaldos restaurar <nombre> [--si]                 vuelve a un respaldo

Qué guarda, en ``BACKUP_DIR`` (``/respaldos`` si se montó una carpeta ahí; si
no, ``/data/respaldos``):

- ``bd/woowkids-AAAAMMDD-HHMMSS.dump``: la base de datos completa (pg_dump en
  formato custom). Se conservan ``BACKUP_DIAS_CONSERVAR`` días y, como mínimo,
  los ``BACKUP_MINIMO_CONSERVAR`` más recientes.
- ``archivos/``: copia incremental del bucket de MinIO (fotos de llegada, INE de
  los tutores, imágenes de productos). Cada respaldo baja solo lo nuevo; las
  llaves nunca se reutilizan, así que la copia sirve para cualquier dump.

El proceso programado revisa cada 10 minutos y respalda cuando el último
respaldo tiene más de ``BACKUP_CADA_HORAS`` horas: no depende de una hora fija,
porque en sucursal el equipo suele apagarse de noche. Cada intento queda en
``public.bitacora_respaldos`` para que la app avise si fallan.

No importa ``app``: corre aunque la API no arranque (por ejemplo, para
restaurar después de una migración fallida).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import mimetypes
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import asyncpg
import pytz

log = logging.getLogger("respaldos")

PREFIJO = "woowkids-"
EXTENSION = ".dump"
INDICE = ".indice.json"
REVISAR_CADA_SEGUNDOS = 600
ESPERA_TRAS_FALLO_SEGUNDOS = 1800


def _entero(nombre: str, defecto: int) -> int:
    try:
        return max(1, int(os.environ.get(nombre, defecto)))
    except ValueError:
        return defecto


def directorio_respaldos() -> Path:
    if os.environ.get("BACKUP_DIR"):
        return Path(os.environ["BACKUP_DIR"])
    if os.path.ismount("/respaldos"):
        return Path("/respaldos")
    if Path("/data").is_dir():
        return Path("/data/respaldos")
    return Path("respaldos").resolve()


def _url_todo_en_uno() -> str | None:
    """En la imagen todo en uno DATABASE_URL solo la recibe el backend; con
    `docker exec` se arma con las mismas variables POSTGRES_*."""
    usuario, clave, bd = (os.environ.get(f"POSTGRES_{v}") for v in ("USER", "PASSWORD", "DB"))
    if not (usuario and clave and bd):
        return None
    return f"postgresql://{quote(usuario, safe='')}:{quote(clave, safe='')}@127.0.0.1:5432/{bd}"


@dataclass(frozen=True)
class Config:
    database_url: str
    dir: Path
    cada_horas: int
    dias_conservar: int
    minimo_conservar: int
    zona: str

    @property
    def dir_bd(self) -> Path:
        return self.dir / "bd"

    @property
    def dir_archivos(self) -> Path:
        return self.dir / "archivos"

    @classmethod
    def desde_entorno(cls) -> Config:
        url = os.environ.get("DATABASE_URL") or _url_todo_en_uno()
        if not url:
            raise SystemExit("[respaldos] DATABASE_URL es obligatoria")
        return cls(
            database_url=url,
            dir=directorio_respaldos(),
            cada_horas=_entero("BACKUP_CADA_HORAS", 6),
            dias_conservar=_entero("BACKUP_DIAS_CONSERVAR", 14),
            minimo_conservar=_entero("BACKUP_MINIMO_CONSERVAR", 3),
            zona=os.environ.get("BACKUP_ZONA_HORARIA", "America/Mexico_City"),
        )


# ── Bitácora en la BD (best effort: nunca impide respaldar) ──────────────────


async def _bitacora_inicio(cfg: Config, motivo: str) -> int | None:
    try:
        conn = await asyncpg.connect(cfg.database_url, timeout=10)
        try:
            fila = await conn.fetchval(
                "INSERT INTO public.bitacora_respaldos (motivo) VALUES ($1) RETURNING id", motivo
            )
            return int(fila)
        finally:
            await conn.close()
    except Exception as exc:  # la tabla aún no existe, BD caída, ...
        log.warning("No se pudo registrar el respaldo en la bitácora: %s", exc)
        return None


async def _bitacora_fin(
    cfg: Config,
    fila: int | None,
    *,
    exitoso: bool,
    nombre: str | None,
    tamano_bd: int | None,
    archivos: int | None,
    error: str | None,
) -> None:
    if fila is None:
        return
    try:
        conn = await asyncpg.connect(cfg.database_url, timeout=10)
        try:
            await conn.execute(
                """
                UPDATE public.bitacora_respaldos
                SET fin = now(), exitoso = $2, nombre = $3, tamano_bd = $4,
                    archivos = $5, error = $6
                WHERE id = $1
                """,
                fila,
                exitoso,
                nombre,
                tamano_bd,
                archivos,
                (error or "")[:2000] or None,
            )
        finally:
            await conn.close()
    except Exception as exc:
        log.warning("No se pudo cerrar el registro de la bitácora: %s", exc)


async def _bitacora_restaurado(cfg: Config, dump: Path) -> None:
    """Tras restaurar, la bitácora es la del respaldo, que se guardó con su
    propia fila sin terminar: se deja constancia de que ese respaldo existe y
    es bueno, para que la app no avise que no hay respaldos."""
    try:
        conn = await asyncpg.connect(cfg.database_url, timeout=10)
        try:
            cuando = datetime.fromtimestamp(dump.stat().st_mtime, UTC)
            await conn.execute(
                """
                INSERT INTO public.bitacora_respaldos
                    (inicio, fin, exitoso, motivo, nombre, tamano_bd)
                VALUES ($1, $1, TRUE, 'restaurado', $2, $3)
                """,
                cuando,
                dump.stem,
                dump.stat().st_size,
            )
        finally:
            await conn.close()
    except Exception as exc:
        log.warning("No se pudo registrar la restauración en la bitácora: %s", exc)


# ── Base de datos ────────────────────────────────────────────────────────────


def _ejecutar(cmd: list[str]) -> None:
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"{cmd[0]} falló: {(resultado.stderr or resultado.stdout).strip()}")


def _nombre_nuevo(cfg: Config, motivo: str) -> str:
    ahora = datetime.now(pytz.timezone(cfg.zona))
    sufijo = "" if motivo == "programado" else f"-{motivo}"
    return f"{PREFIJO}{ahora:%Y%m%d-%H%M%S}{sufijo}"


def respaldar_bd(cfg: Config, nombre: str) -> Path:
    cfg.dir_bd.mkdir(parents=True, exist_ok=True)
    destino = cfg.dir_bd / f"{nombre}{EXTENSION}"
    parcial = destino.with_suffix(".parcial")
    try:
        _ejecutar(["pg_dump", f"--dbname={cfg.database_url}", "-Fc", "-f", str(parcial)])
        parcial.replace(destino)
    finally:
        parcial.unlink(missing_ok=True)
    return destino


def dumps(cfg: Config) -> list[Path]:
    """Dumps completos, del más reciente al más antiguo."""
    if not cfg.dir_bd.is_dir():
        return []
    return sorted(
        cfg.dir_bd.glob(f"{PREFIJO}*{EXTENSION}"), key=lambda p: p.stat().st_mtime, reverse=True
    )


def _es_programado(dump: Path) -> bool:
    """``woowkids-AAAAMMDD-HHMMSS.dump``, sin sufijo de motivo."""
    return dump.stem.count("-") == 2


def depurar(cfg: Config) -> list[Path]:
    """Borra los dumps más viejos que ``dias_conservar``, dejando siempre los
    ``minimo_conservar`` más recientes."""
    limite = time.time() - cfg.dias_conservar * 86400
    borrados = []
    for viejo in dumps(cfg)[cfg.minimo_conservar :]:
        if viejo.stat().st_mtime < limite:
            viejo.unlink(missing_ok=True)
            borrados.append(viejo)
    return borrados


# ── Archivos (MinIO) ─────────────────────────────────────────────────────────


def _s3() -> tuple[Any, str]:
    import boto3
    from botocore.client import Config as BotoConfig

    seguro = os.environ.get("MINIO_SECURE", "false").lower() == "true"
    servidor = os.environ.get("MINIO_ENDPOINT", "minio:9000")
    cliente = boto3.client(
        "s3",
        endpoint_url=f"http{'s' if seguro else ''}://{servidor}",
        aws_access_key_id=os.environ.get("MINIO_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("MINIO_SECRET_KEY"),
        config=BotoConfig(signature_version="s3v4"),
    )
    return cliente, os.environ.get("MINIO_BUCKET", "mercury")


def ruta_segura(base: Path, llave: str) -> Path:
    """Ruta local de un objeto; rechaza llaves que saldrían de ``base``."""
    partes = PurePosixPath(llave).parts
    if not partes or llave.startswith("/") or any(p in ("..", "") for p in partes):
        raise ValueError(f"Llave de objeto no válida: {llave!r}")
    if partes[-1] == INDICE or partes[-1].endswith(".parcial"):
        raise ValueError(f"Llave de objeto reservada: {llave!r}")
    return base.joinpath(*partes)


def _leer_indice(base: Path) -> dict[str, dict[str, Any]]:
    try:
        return dict(json.loads((base / INDICE).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def _guardar_indice(base: Path, indice: dict[str, dict[str, Any]]) -> None:
    tmp = base / f"{INDICE}.parcial"
    tmp.write_text(json.dumps(indice, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(base / INDICE)


def respaldar_archivos(cfg: Config) -> tuple[int, int]:
    """Copia al respaldo los objetos nuevos o cambiados. Devuelve (total, nuevos)."""
    from botocore.exceptions import ClientError

    cliente, bucket = _s3()
    base = cfg.dir_archivos
    base.mkdir(parents=True, exist_ok=True)
    indice = _leer_indice(base)
    total = nuevos = 0
    try:
        paginas = cliente.get_paginator("list_objects_v2").paginate(Bucket=bucket)
        for pagina in paginas:
            for obj in pagina.get("Contents", []):
                llave, etag, tamano = obj["Key"], obj["ETag"].strip('"'), obj["Size"]
                destino = ruta_segura(base, llave)
                total += 1
                previo = indice.get(llave)
                if (
                    previo
                    and previo.get("etag") == etag
                    and destino.is_file()
                    and destino.stat().st_size == tamano
                ):
                    continue
                destino.parent.mkdir(parents=True, exist_ok=True)
                parcial = destino.with_name(destino.name + ".parcial")
                respuesta = cliente.get_object(Bucket=bucket, Key=llave)
                with parcial.open("wb") as f:
                    shutil.copyfileobj(respuesta["Body"], f)
                parcial.replace(destino)
                indice[llave] = {
                    "etag": etag,
                    "size": tamano,
                    "content_type": respuesta.get("ContentType"),
                }
                nuevos += 1
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchBucket":
            raise
    finally:
        _guardar_indice(base, indice)
    return total, nuevos


def restaurar_archivos(cfg: Config) -> int:
    from botocore.exceptions import ClientError

    cliente, bucket = _s3()
    try:
        cliente.head_bucket(Bucket=bucket)
    except ClientError:
        cliente.create_bucket(Bucket=bucket)
    base = cfg.dir_archivos
    if not base.is_dir():
        return 0
    indice = _leer_indice(base)
    subidos = 0
    for archivo in sorted(base.rglob("*")):
        if not archivo.is_file() or archivo.name.endswith(".parcial") or archivo.name == INDICE:
            continue
        llave = archivo.relative_to(base).as_posix()
        tipo = (indice.get(llave) or {}).get("content_type") or (
            mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
        )
        cliente.upload_file(str(archivo), bucket, llave, ExtraArgs={"ContentType": tipo})
        subidos += 1
    return subidos


# ── Comandos ─────────────────────────────────────────────────────────────────


def respaldar(cfg: Config, motivo: str, solo_bd: bool = False) -> Path:
    nombre = _nombre_nuevo(cfg, motivo)
    fila = asyncio.run(_bitacora_inicio(cfg, motivo))
    try:
        dump = respaldar_bd(cfg, nombre)
        total = nuevos = None
        if not solo_bd:
            total, nuevos = respaldar_archivos(cfg)
        borrados = depurar(cfg)
    except Exception as exc:
        log.error("Respaldo %s FALLÓ: %s", nombre, exc)
        asyncio.run(
            _bitacora_fin(
                cfg,
                fila,
                exitoso=False,
                nombre=nombre,
                tamano_bd=None,
                archivos=None,
                error=str(exc),
            )
        )
        raise
    tamano = dump.stat().st_size
    asyncio.run(
        _bitacora_fin(
            cfg, fila, exitoso=True, nombre=nombre, tamano_bd=tamano, archivos=total, error=None
        )
    )
    archivos = "" if solo_bd else f", archivos: {total} ({nuevos} nuevos)"
    log.info(
        "Respaldo %s listo en %s (BD: %.1f MB%s; depurados: %d)",
        nombre,
        cfg.dir,
        tamano / 1_048_576,
        archivos,
        len(borrados),
    )
    return dump


def _esperar_api() -> None:
    """Con ``BACKUP_ESPERAR_URL`` (todo en uno), espera a que la API responda:
    el backend solo arranca después de crear la BD y aplicar las migraciones,
    y un respaldo a medio migrar no sirve."""
    import urllib.request

    url = os.environ.get("BACKUP_ESPERAR_URL")
    if not url:
        return
    avisado = False
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as respuesta:
                if respuesta.status == 200:
                    return
        except Exception:
            pass
        if not avisado:
            log.info("Esperando a que el backend termine de arrancar (%s)", url)
            avisado = True
        time.sleep(5)


def programado(cfg: Config) -> None:
    espera_inicial = _entero("BACKUP_ESPERA_INICIAL_SEGUNDOS", 120)
    log.info(
        "Respaldos automáticos cada %d h en %s (se conservan %d días). Primera revisión en %d s.",
        cfg.cada_horas,
        cfg.dir,
        cfg.dias_conservar,
        espera_inicial,
    )
    if not os.path.ismount("/respaldos") and not os.environ.get("BACKUP_DIR"):
        log.warning(
            "Los respaldos quedan en el mismo volumen que los datos: si se pierde el disco, "
            "se pierden también. Monta una carpeta del equipo (o de otro disco) en /respaldos."
        )
    time.sleep(espera_inicial)
    while True:
        # Solo cuentan los programados (BD + archivos): uno manual o el que se
        # hace antes de migrar puede ser solo de la BD.
        recientes = [d for d in dumps(cfg) if _es_programado(d)]
        ultimo = datetime.fromtimestamp(recientes[0].stat().st_mtime, UTC) if recientes else None
        if ultimo is None or datetime.now(UTC) - ultimo >= timedelta(hours=cfg.cada_horas):
            _esperar_api()
            try:
                respaldar(cfg, "programado")
            except Exception:
                time.sleep(ESPERA_TRAS_FALLO_SEGUNDOS)
                continue
        time.sleep(REVISAR_CADA_SEGUNDOS)


def listar(cfg: Config) -> None:
    disponibles = dumps(cfg)
    print(f"Respaldos en {cfg.dir_bd}:")
    if not disponibles:
        print("  (ninguno todavía)")
    zona = pytz.timezone(cfg.zona)
    for d in disponibles:
        cuando = datetime.fromtimestamp(d.stat().st_mtime, zona)
        print(f"  {d.stem:<45} {cuando:%Y-%m-%d %H:%M}  {d.stat().st_size / 1_048_576:8.1f} MB")
    archivos = _leer_indice(cfg.dir_archivos)
    print(f"Archivos respaldados: {len(archivos)} en {cfg.dir_archivos}")


def _url_mantenimiento(url: str) -> tuple[str, str]:
    """URL a la BD ``postgres`` del mismo servidor y el nombre de la BD de la app."""
    partes = urlsplit(url)
    bd = partes.path.lstrip("/")
    if not bd:
        raise SystemExit("[respaldos] DATABASE_URL no indica la base de datos")
    return urlunsplit(partes._replace(path="/postgres")), bd


def _url_con_bd(url: str, bd: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{bd}"))


def _cargar_dump(dump: Path, url: str) -> None:
    """Carga el dump en la BD vacía ``url`` en una sola transacción.

    Va como SQL (pg_restore -f -) a psql y no con pg_restore directo porque el
    pg_dump de la imagen puede ser más nuevo que el servidor (compose usa
    PostgreSQL 16): el dump trae ``SET transaction_timeout``, que el 16 no
    reconoce. Esa línea solo fija un parámetro de la sesión y se omite."""
    import tempfile

    with tempfile.TemporaryFile() as err_restore, tempfile.TemporaryFile() as err_psql:
        restore = subprocess.Popen(
            ["pg_restore", "--no-owner", "-f", "-", str(dump)],
            stdout=subprocess.PIPE,
            stderr=err_restore,
        )
        psql = subprocess.Popen(
            ["psql", url, "-v", "ON_ERROR_STOP=1", "-q", "--single-transaction"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=err_psql,
        )
        assert restore.stdout is not None and psql.stdin is not None
        try:
            for linea in restore.stdout:
                if not linea.startswith(b"SET transaction_timeout"):
                    psql.stdin.write(linea)
        except BrokenPipeError:
            pass  # psql ya terminó por un error; se reporta abajo
        finally:
            try:
                psql.stdin.close()
            except BrokenPipeError:
                pass
        codigo_restore, codigo_psql = restore.wait(), psql.wait()
        for codigo, err, nombre in (
            (codigo_restore, err_restore, "pg_restore"),
            (codigo_psql, err_psql, "psql"),
        ):
            if codigo != 0:
                err.seek(0)
                detalle = err.read().decode("utf-8", "replace").strip()
                raise RuntimeError(f"{nombre} falló: {detalle}")


def _restaurar_bd(cfg: Config, dump: Path) -> None:
    """Carga el respaldo en una BD temporal y solo si salió bien reemplaza a la
    actual: un respaldo dañado o incompatible no deja el sistema sin datos."""
    mantenimiento, bd = _url_mantenimiento(cfg.database_url)
    temporal = f"{bd}_restaurando"
    psql = ["psql", mantenimiento, "-v", "ON_ERROR_STOP=1", "-q"]
    borrar_temporal = ["-c", f'DROP DATABASE IF EXISTS "{temporal}" WITH (FORCE)']
    _ejecutar([*psql, *borrar_temporal, "-c", f'CREATE DATABASE "{temporal}"'])
    try:
        _cargar_dump(dump, _url_con_bd(cfg.database_url, temporal))
    except Exception:
        try:
            _ejecutar([*psql, *borrar_temporal])
        finally:
            print("[respaldos] No se restauró nada: los datos actuales siguen igual.")
        raise
    _ejecutar(
        [
            *psql,
            "-c",
            f'DROP DATABASE IF EXISTS "{bd}" WITH (FORCE)',
            "-c",
            f'ALTER DATABASE "{temporal}" RENAME TO "{bd}"',
        ]
    )


def _supervisorctl(accion: str) -> bool:
    """Detiene o arranca el backend (y el respaldo programado) en la imagen
    todo en uno. False si no hay supervisor (compose: se detiene a mano)."""
    if not shutil.which("supervisorctl") or not Path("/tmp/supervisor.sock").exists():
        return False
    resultado = subprocess.run(
        ["supervisorctl", accion, "backend", "respaldos"], capture_output=True, text=True
    )
    print(f"[respaldos] {(resultado.stdout or resultado.stderr).strip()}")
    return resultado.returncode == 0


def restaurar(cfg: Config, nombre: str, confirmado: bool) -> None:
    candidato = Path(nombre)
    if not candidato.is_file():
        candidato = cfg.dir_bd / (nombre if nombre.endswith(EXTENSION) else nombre + EXTENSION)
    if not candidato.is_file():
        raise SystemExit(f"[respaldos] No existe el respaldo {nombre!r}. Usa: respaldos listar")
    if not confirmado:
        print(
            f"Se REEMPLAZARÁN todos los datos actuales por los del respaldo {candidato.stem}.\n"
            "Antes se guarda un respaldo del estado actual (motivo antes-de-restaurar)."
        )
        if input("Escribe RESTAURAR para continuar: ").strip() != "RESTAURAR":
            raise SystemExit("[respaldos] Cancelado.")

    previo = respaldar(cfg, "antes-de-restaurar", solo_bd=True)
    print(f"[respaldos] Estado actual guardado en {previo.name}")

    con_supervisor = _supervisorctl("stop")
    if not con_supervisor:
        print("[respaldos] Detén el backend antes de restaurar (docker compose stop backend).")
    try:
        _restaurar_bd(cfg, candidato)
        print(f"[respaldos] Base de datos restaurada desde {candidato.name}")
        asyncio.run(_bitacora_restaurado(cfg, candidato))
        subidos = restaurar_archivos(cfg)
        print(f"[respaldos] Archivos restaurados: {subidos}")
    finally:
        if con_supervisor:
            _supervisorctl("start")
    print(
        "[respaldos] Listo. Al arrancar, el backend aplica las migraciones que le falten al "
        "respaldo. Quien inició sesión después del respaldo debe volver a entrar."
    )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="[respaldos] %(levelname)s %(message)s", stream=sys.stdout
    )
    parser = argparse.ArgumentParser(prog="respaldos", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="comando", required=True)
    p_resp = sub.add_parser("respaldar", help="hace un respaldo ahora")
    p_resp.add_argument("--motivo", default="manual")
    p_resp.add_argument("--solo-bd", action="store_true", help="sin copiar los archivos de MinIO")
    sub.add_parser("programado", help="respalda solo cada BACKUP_CADA_HORAS horas")
    sub.add_parser("listar", help="muestra los respaldos disponibles")
    p_rest = sub.add_parser("restaurar", help="reemplaza los datos por los de un respaldo")
    p_rest.add_argument("nombre", help="nombre que muestra 'respaldos listar' (o ruta al .dump)")
    p_rest.add_argument("--si", action="store_true", help="no pedir confirmación")
    args = parser.parse_args(argv)

    cfg = Config.desde_entorno()
    if args.comando == "respaldar":
        try:
            respaldar(cfg, args.motivo, solo_bd=args.solo_bd)
        except Exception:
            raise SystemExit(1) from None
    elif args.comando == "programado":
        programado(cfg)
    elif args.comando == "listar":
        listar(cfg)
    else:
        try:
            restaurar(cfg, args.nombre, args.si)
        except RuntimeError as exc:
            raise SystemExit(f"[respaldos] La restauración falló: {exc}") from None


if __name__ == "__main__":
    main()
