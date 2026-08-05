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

    # La UNICA variable del proveedor de embeddings. El modelo, la dimension y
    # las plantillas viven en codigo (ADR-0012): configurables por `env`
    # podrian cambiarse sin que suba `retrieval_index_version`, y entonces los
    # tres sellos de la decision mentirian a la vez.
    #
    # Opcional porque el sistema funciona sin ella: sin clave no hay indice, y
    # eso deja el descubrimiento vacio pero no el servicio roto. El estado tiene
    # nombre y metrica —chunks pendientes de indexar, entregable 6— asi que
    # fallar al arrancar seria convertir un estado previsto en una caida.
    gemini_api_key: str | None = None

    # El segundo proveedor: generacion. `gemini_api_key` cubre recuperacion.
    # Misma regla que aquella —el modelo y el prompt viven en codigo, porque
    # cambiarlos por `env` haria mentir a `explanation_prompt_version`— y misma
    # nulabilidad: sin clave, la explicacion al cliente cae a plantilla y el
    # sistema sigue decidiendo. Fallar al arrancar convertiria una degradacion
    # prevista en una caida.
    anthropic_api_key: str | None = None

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
