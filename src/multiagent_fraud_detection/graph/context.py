"""Dependencias de runtime del grafo.

No es estado: no muta entre nodos, no se checkpointea y puede contener objetos
no serializables. Es lo que el grafo necesita del mundo exterior.

Se inyecta al invocar:

    await graph.ainvoke(entrada, context=GraphContext(session_factory=...))

El nodo persistidor no puede usar la sesion del request: ese ya devolvio 202 y
el grafo corre en segundo plano. Necesita su propia sesion y su propio commit.
"""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from multiagent_fraud_detection.db.repositories.merchant_blacklist import BlacklistCache
from multiagent_fraud_detection.domain.catalog import PolicyCatalog, load_catalog
from multiagent_fraud_detection.retrieval.embeddings import Embedder, GeminiEmbedder
from multiagent_fraud_detection.retrieval.query import QueryCache, code_vocabulary

# Fase 2 de ADR-0007: el catalogo se lee de archivos versionados. La fase 3 lo
# mueve a las tablas `fraud_policies` / `policy_bindings`, y entonces esto pasa a
# ser una consulta. Se aisla aca para que ese cambio toque un solo lugar.
POLICIES_DIR = Path(__file__).resolve().parents[3] / "data" / "policies"


def load_default_catalog() -> PolicyCatalog:
    return load_catalog(
        POLICIES_DIR / "fraud_policies_2025.1.json",
        POLICIES_DIR / "policy_bindings_2025.1.json",
    )


@dataclass
class GraphContext:
    session_factory: async_sessionmaker[AsyncSession]

    # Con default para no romper a quien ya construye el contexto con un solo
    # argumento, pero **el proceso real deberia cargarlo una vez al arrancar** y
    # pasarlo: cargar el catalogo por caso relee y revalida dos archivos.
    catalog: PolicyCatalog = field(default_factory=load_default_catalog)

    # Cache por proceso: una instancia por contexto, no un global de modulo.
    blacklist: BlacklistCache = field(default_factory=BlacklistCache)

    # El proveedor de embeddings, detras del puerto. Se inyecta para que un
    # test pueda pasar `FakeEmbedder()` sin red ni clave, y para que cambiar de
    # proveedor sea un adaptador y una version de indice nueva (ADR-0012).
    embedder: Embedder = field(default_factory=GeminiEmbedder)

    # Embeddings de query por combinacion de codigos de senal. Sin TTL, a
    # diferencia del de la lista negra: la entrada no puede quedar obsoleta por
    # una escritura de otra replica, porque depende solo del vocabulario y de
    # `INDEX_VERSION`, y los dos son constantes del proceso.
    query_cache: QueryCache = field(default_factory=QueryCache)

    # `codigo de senal -> frase del predicado`, derivado del catalogo activo. Se
    # calcula una vez porque recorre las once politicas y sus condiciones.
    #
    # `init=False`: depende de `catalog`, asi que no puede ser un
    # `default_factory` —no recibiria el catalogo que se acaba de construir— y
    # tampoco tiene sentido que el llamador lo pase por separado, porque
    # entonces podrian no corresponderse.
    vocabulary: dict[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.vocabulary = code_vocabulary(self.catalog)
