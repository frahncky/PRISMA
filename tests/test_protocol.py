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
