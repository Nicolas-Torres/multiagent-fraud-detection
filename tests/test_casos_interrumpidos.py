"""El barrido de casos interrumpidos por un reinicio (`api/casos_interrumpidos.py`).

Sin base: se verifica la sentencia que se envía y que un fallo nunca impide
arrancar. Contra Postgres real lo comprueba el arranque en producción.
"""

from sqlalchemy.dialects import postgresql

from multiagent_fraud_detection.api import casos_interrumpidos


def _sql() -> str:
    return str(
        casos_interrumpidos.sentencia().compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_cierra_solo_los_casos_en_curso_como_failed():
    sql = _sql()
    assert "UPDATE cases SET status='FAILED'" in sql
    assert "cases.status IN ('RECEIVED', 'ANALYZING')" in sql


def test_solo_toca_casos_sin_cambios_hace_diez_minutos():
    """Sin este filtro, una réplica que arranca cerraría el análisis que la
    otra nube está corriendo en este momento."""
    sql = _sql()
    assert "cases.updated_at < now() -" in sql
    assert casos_interrumpidos.ANTIGUEDAD_MINIMA.total_seconds() == 600


class _FabricaQueFalla:
    def __call__(self):
        raise ConnectionError("Postgres no responde")


async def test_un_fallo_de_la_base_no_impide_arrancar():
    assert await casos_interrumpidos.cerrar_interrumpidos(_FabricaQueFalla()) == 0
