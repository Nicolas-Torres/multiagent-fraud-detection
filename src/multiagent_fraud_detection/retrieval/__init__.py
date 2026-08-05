"""La capa de recuperación: chunking, embeddings y búsqueda vectorial.

Todo lo que ADR-0012 declara **parámetro de derivación** vive acá: el modelo, la
dimensión, las plantillas de prompt y la estrategia de chunking. Los cuatro suben
`index_version`, y `embeddings.py` compone esa cadena a partir de las mismas
constantes que usan el indexador y el buscador — de modo que no se puede cambiar
uno sin que la versión lo refleje.
"""
