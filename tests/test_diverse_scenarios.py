"""Los escenarios diversos del dashboard pueden cumplir lo que prometen
(incidente 0008).

Cada corrida en vivo sufija dispositivo y comercio, así que un escenario cuya
señal depende de ellos nunca la reproduce. Sin red ni base: el selector lee el
dataset y el ground truth del repo.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _dataset import leer_ground_truth
from seed_diverse_scenarios import JSON_PATH, _id_corto, elegir

#: Declarado acá y no importado del selector: si alguien vaciara la constante
#: del script, este test tiene que seguir fallando. FP-03 mira la historia del
#: dispositivo; FP-07, la identidad del comercio; FP-11, su historia del día.
DEPENDEN_DE_DISPOSITIVO_O_COMERCIO = {"FP-03", "FP-07", "FP-11"}


def test_ningun_escenario_depende_del_dispositivo_o_del_comercio():
    politicas_por_id = {
        _id_corto(tid): gt["policies"] for tid, gt in leer_ground_truth().items()
    }

    elegidas = {e["id"]: politicas_por_id[e["id"]] for e in elegir()}

    assert elegidas
    assert not {
        id_: politicas
        for id_, politicas in elegidas.items()
        if DEPENDEN_DE_DISPOSITIVO_O_COMERCIO.intersection(politicas)
    }


def test_el_json_del_dashboard_es_el_que_genera_el_selector():
    """Sin esto, cambiar el selector sin regenerar dejaría al dashboard con los
    escenarios viejos, y el test de arriba pasaría igual."""
    assert json.loads(JSON_PATH.read_text(encoding="utf-8")) == elegir()
