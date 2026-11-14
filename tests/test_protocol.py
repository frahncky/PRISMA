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
