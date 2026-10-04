from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor de fábrica de SECRET_KEY en las imágenes y el compose. El entrypoint lo
# reemplaza por una clave aleatoria guardada en la BD (tabla secretos_sistema),
# así que la API nunca debe arrancar con él: quien lo conozca fabricaría tokens.
SECRET_KEY_DE_FABRICA = "woowkids-secret-key-cambiar-en-produccion"


class Settings(BaseSettings):
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    access_token_remember_me_minutes: int = 60 * 24 * 7  # 7 días
    refresh_token_expire_days: int = 7
    refresh_token_remember_me_days: int = 30

    # QA #32 — seguridad de sesión (WP B8). Todo detrás de flags, default
    # retrocompatible con los clientes viejos (body-only, sin cookie).
    cookie_secure: bool = True
    refresh_en_body: bool = True
    ws_acepta_jwt: bool = True
    ws_ticket_ttl_seconds: int = 30

    database_url: str
    # Pool de conexiones a PostgreSQL. Un solo proceso atiende todas las
    # sucursales: con el máximo por defecto de asyncpg (10) y sin tiempo límite
    # para obtener conexión, la API se quedaba colgada en cuanto se agotaba.
    db_pool_min_size: int = 2
    db_pool_max_size: int = 20
    # Segundos que una petición espera una conexión libre antes de responder 503.
    db_pool_acquire_timeout: float = 15
    # Segundos máximos de una consulta (los reportes más pesados tardan < 10 s).
    db_command_timeout: float = 120

    cors_origins: list[str] = ["http://localhost:5173"]

    minio_endpoint: str = "minio:9000"
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str = "mercury"
    minio_secure: bool = False

    # QA #14: exige token_pin de cajero y admin en POST /turnos-caja/confirmar.
    # Retrocompatibilidad: en false, confirmar acepta la ausencia de tokens.
    exigir_pin_token: bool = True

    @field_validator("secret_key")
    @classmethod
    def _rechazar_secret_key_de_fabrica(cls, v: str) -> str:
        if not v.strip() or v == SECRET_KEY_DE_FABRICA:
            raise ValueError(
                "SECRET_KEY vacía o de fábrica: arranca con docker/entrypoint.sh "
                "(la genera sola) o define una propia."
            )
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
