from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    database_url: str
    log_level: str = "INFO"

    # Donde esta corriendo el proceso. Habilita las operaciones destructivas
    # (ADR-0010) y sirve para etiquetar trazas y logs.
    #
    # El default es `"unknown"` y **no** `"local"` a proposito: la variable
    # ausente tiene que RECHAZAR, no permitir. Un default permisivo convertiria
    # el olvido de configurar en autorizacion, que es justo el escenario contra
    # el que existe el guard.
    #
    # No es obligatoria porque hacerla requerida romperia el arranque de todo
    # script hasta que cada `.env` se actualice; y una variable ausente ya
    # produce el comportamiento seguro sin necesidad de fallar.
    environment: str = "unknown"

    @property
    def permite_operaciones_destructivas(self) -> bool:
        """Lista blanca: solo `local`.

        La formulacion intuitiva —*prohibir en `production` y `staging`*— falla
        abierto: la variable sin setear, un ambiente llamado `prod`, `qa` o
        `demo`, y el `.env` equivocado pasan todos el filtro. Invertida, para
        destruir datos hay que declarar activamente donde se esta parado.
        """
        return self.environment == "local"


settings = Settings()
