"""Reglas puras del motor determinístico.

Sin I/O: nada de acá abre una conexión, lee un archivo ni llama a un LLM. Es lo
que hace que la capa se pueda probar sobre las 7 000 transacciones del dataset
en segundos, sin base de datos y sin red.
"""
