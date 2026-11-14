import pytest
from prisma.core.protocol import parse_sample, Sample

def test_amostra_valida():
    s = parse_sample(b'{"type":"sample","t":0.01,"va":1,"vb":-2,"vc":0}')
    assert s == Sample(t=0.01, va=1.0, vb=-2.0, vc=0.0)

@pytest.mark.parametrize("msg", [
    '{}',
    '{"type":"sample","t":0,"va":0,"vb":0}',
    '{"type":"sample","t":0,"va":true,"vb":0,"vc":0}',
    '{"type":"other","t":0,"va":0,"vb":0,"vc":0}',
    '{"type":"sample","t":"0","va":0,"vb":0,"vc":0}',
])
def test_rejeita_mensagens_invalidas(msg):
    with pytest.raises((ValueError, KeyError)):
        parse_sample(msg)


def test_status_demoem_preserva_mensagem_sinal_e_mascaras():
    from prisma.core.protocol import HardwareStatus, parse_message

    status = parse_message('{"type":"status","source":"DEMOEM","message":"ADC RAW",'
        '"adc":{"dadp0_raw":65535},"adc_signed":{"dadp0":-1},"adc_timeout_mask":0,"adc_cal_fail_mask":2}')
    assert isinstance(status, HardwareStatus)
    assert status.message == "ADC RAW"
    assert status.adc == {"dadp0_raw": 65535.0, "dadp0_signed": -1.0}
    assert status.diagnostics == {"adc_timeout_mask": 0.0, "adc_cal_fail_mask": 2.0}


def _burst(seq=0, n=4, fs_mhz=2_000_000, values=None):
    import json
    values = values or [i * 3 + c for i in range(n) for c in range(3)]
    return json.dumps({"type": "burst", "source": "DEMOEM", "seq": seq, "fs_mhz": fs_mhz, "n": n,
                       "ch": ["ad4", "ad5", "ad6"], "adc_timeout_mask": 0,
                       "data": "".join(f"{v:04X}" for v in values)})


def test_rajada_decodifica_hex_e_tempo():
    from prisma.core.protocol import BURST_SPACING_S, SampleBlock, parse_message

    block = parse_message(_burst(seq=2, n=4, values=[0, 1, 0xFFFF, 10, 11, 12, 20, 21, 22, 30, 31, 32]))
    assert isinstance(block, SampleBlock) and block.fs_hz == 2000.0
    assert block.channels == ("ad4", "ad5", "ad6")
    assert block.samples[0].vc == 65535.0 and block.samples[3].va == 30.0
    assert block.samples[0].t == 2 * BURST_SPACING_S
    assert abs(block.samples[1].t - block.samples[0].t - 0.0005) < 1e-12


@pytest.mark.parametrize("change", [{"n": 5}, {"ch": ["a", "b"]}, {"fs_mhz": 0}, {"data": "ZZZZ" * 12}, {"seq": -1}])
def test_rajada_invalida_e_rejeitada(change):
    import json
    from prisma.core.protocol import parse_message

    payload = json.loads(_burst())
    payload.update(change)
    with pytest.raises(ValueError):
        parse_message(json.dumps(payload))
