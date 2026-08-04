from src.observability import configurar_langsmith  # noqa: F401  (activa el trazado al importar)

configurar_langsmith()


def main() -> None:
    print("Hello from multiagent-fraud-detection!")
