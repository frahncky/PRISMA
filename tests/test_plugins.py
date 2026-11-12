import json
import pytest
from prisma.core.devices import DeviceProfile, load_protocol
from prisma.core.protocol import Sample


def test_plugin_csv_instalado_e_perfil(tmp_path):
    parser = load_protocol('csv-trifasico-v1')
    assert parser(b'0.001,127,-60,0\n') == Sample(.001, 127, -60, 0)
    assert parser(b'0.001,127,-60,0,5,-2,0').ia == 5
    for invalid in (b'header,va,vb,vc', b'0,1,2', b'0,NaN,2,3', b'0,1,2,3,4'):
        with pytest.raises(ValueError):
            parser(invalid)
    profile = tmp_path / 'csv.json'
    profile.write_text(json.dumps({'version': 1, 'name': 'CSV', 'protocol': 'csv-trifasico-v1'}))
    assert DeviceProfile.load(profile).protocol == 'csv-trifasico-v1'


def test_registro_nao_importa_plugins_nao_selecionados_e_rejeita_duplicados(monkeypatch):
    loaded = []

    class Point:
        def __init__(self, name):
            self.name = name
        def load(self):
            loaded.append(self.name)
            return lambda line: Sample(0, 1, 2, 3)

    points = [Point('escolhido'), Point('outro')]
    monkeypatch.setattr('prisma.core.devices.entry_points', lambda **k: points)
    assert load_protocol('escolhido')(b'') == Sample(0, 1, 2, 3)
    assert loaded == ['escolhido']
    points.append(Point('escolhido'))
    with pytest.raises(ValueError):
        load_protocol('escolhido')
    with pytest.raises(ValueError):
        load_protocol('ausente')
