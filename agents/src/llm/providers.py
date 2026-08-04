"""Factory de proveedor LLM configurable por entorno (D10).

- **Dev** (`LLM_PROVIDER=openai-compatible`): el endpoint `ANTHROPIC_API_BASE`
  apunta a `https://opencode.ai/zen/go/v1`, que sirve una API compatible con
  OpenAI. Se usa `ChatOpenAI` con `base_url` + `api_key` + modelo.
- **Despliegue** (`LLM_PROVIDER=anthropic`): la misma factory apunta a la API
  real de Claude con `ChatAnthropic`.

Los prompts y los esquemas de salida estructurada **no cambian** entre
entornos: solo cambia el cliente. Los embeddings siempre usan Gemini
(`EMBEDDING_MODEL`/`EMBEDDING_DIM`).
"""

from src.config.settings import settings


def build_llm():
    """Construye el cliente de chat según `LLM_PROVIDER`."""
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.anthropic_model or "claude-sonnet-4-5",
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_api_base,
            temperature=0.0,
            max_retries=2,
            timeout=60,
        )

    # openai-compatible (dev): opencode sirve el protocolo de OpenAI.
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.anthropic_model or "qwen3.6-plus",
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_api_base,
        temperature=0.0,
        max_retries=2,
        timeout=60,
    )


def build_embeddings():
    """Cliente de embeddings (Gemini, `EMBEDDING_MODEL`/`EMBEDDING_DIM`).

    `EMBEDDING_DIM=3072` es la dimensión **nativa** de `gemini-embedding-2`.
    No se trunca: pgvector no permite índices HNSW/IVFFlat por encima de 2000
    dimensiones, así que a 3072 la búsqueda es un scan coseno secuencial (exacto)
    —suficiente para un corpus de 11 políticas (D8).
    """
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.gemini_api_key,
        output_dimensionality=settings.embedding_dim,
    )
