#pragma once
#include <Arduino.h>

// HMI touch pelo navegador local. Não é driver para TFT físico.
static const char PRISMA_DASHBOARD[] PROGMEM = R"HTML(
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>PRISMA • Painel</title>
<style>
:root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#e9f5fb;background:#091524}
*{box-sizing:border-box}body{margin:0;padding:22px;min-height:100vh}
main{max-width:1100px;margin:0 auto}
header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;margin-bottom:24px}
h1{font-size:30px;margin:0;letter-spacing:.04em}p{color:#a6bbca;margin:6px 0 0}
#state{background:#20374b;padding:8px 14px;border-radius:99px;font-size:13px}
nav{display:flex;gap:10px;margin:18px 0}
button{min-height:50px;padding:10px 22px;font-size:16px;border-radius:10px;border:1px solid #3d5b74;color:#e9f5fb;background:#152b41;cursor:pointer;touch-action:manipulation}
button[aria-selected="true"]{background:#076b85;border-color:#35cce7}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.card{border:1px solid #284359;border-radius:14px;padding:20px;background:#132638}
.card h2{margin:0 0 14px;font-size:17px;color:#b0c4d2}
.value{font-size:clamp(25px,4.5vw,42px);font-weight:750;color:#fff}
.unit{font-size:15px;color:#94adbd}
small{display:block;margin-top:12px;color:#a9c1cc;line-height:1.6}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.6}
[hidden]{display:none!important}.warning{margin-top:16px;color:#ffc87d}
@media(max-width:700px){body{padding:14px}.grid{grid-template-columns:1fr}h1{font-size:24px}}
</style></head><body><main>
<header><div><h1>◈ PRISMA</h1><p>Interface touch de monitoramento • DEMOEM → ESP32-S3</p></div><div id="state">Conectando…</div></header>
<nav aria-label="Navegação"><button id="measureBtn" aria-selected="true" onclick="tab('measure')">Medições</button>
<button id="networkBtn" aria-selected="false" onclick="tab('network')">Dispositivo e IoT</button></nav>
<section id="measure">
<div class="grid">
<article class="card"><h2>Fase A</h2><div class="value" id="va">—</div><span class="unit">V RMS</span><small id="ia">Corrente: —</small><small id="pa">Potência ativa: —</small></article>
<article class="card"><h2>Fase B</h2><div class="value" id="vb">—</div><span class="unit">V RMS</span><small id="ib">Corrente: —</small><small id="pb">Potência ativa: —</small></article>
<article class="card"><h2>Fase C</h2><div class="value" id="vc">—</div><span class="unit">V RMS</span><small id="ic">Corrente: —</small><small id="pc">Potência ativa: —</small></article>
</div>
<p class="warning">Valores estimados em janela temporal. Não são medições certificadas. Exige sensores condicionados, calibração e firmware ColdFire reais.</p>
</section>
<section id="network" hidden><article class="card"><h2>Diagnóstico</h2><pre id="diagnostics">Aguardando dados…</pre></article>
<p class="warning">A interface HTTP não possui autenticação: use apenas em rede local isolada e confiável. MQTT exige TLS e certificado CA.</p></section>
</main><script>
function tab(which){
 const m=which==='measure';
 document.getElementById('measure').hidden=!m;
 document.getElementById('network').hidden=m;
 document.getElementById('measureBtn').setAttribute('aria-selected',String(m));
 document.getElementById('networkBtn').setAttribute('aria-selected',String(!m));
}
function set(id,value){document.getElementById(id).textContent=value}
function fmt(value,digits=1){return typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits):'—'}
async function refresh(){
 try{
  const res=await fetch('/api/status',{cache:'no-store'});
  if(!res.ok)throw Error('HTTP '+res.status);
  const d=await res.json(),fresh=d.fresh===true;
  set('state',fresh?'SERIAL ATIVA':'SEM AMOSTRAS RECENTES');
  ['a','b','c'].forEach((phase,j)=>{
   set('v'+phase, fresh?fmt(d.vrms_V?.[j]):'—');
   set('i'+phase,fresh&&d.irms_A?'Corrente: '+fmt(d.irms_A[j],2)+' A':'Corrente: indisponível');
   set('p'+phase,fresh&&d.p_W?'Potência ativa: '+fmt(d.p_W[j])+' W':'Potência ativa: indisponível');
  });
  set('diagnostics',JSON.stringify({
    dispositivo:d.device_id,origem:d.source,amostras:d.samples,
    amostras_da_janela:d.window_samples,idade_da_ultima_amostra_ms:d.age_ms,
    resets_de_tempo:d.time_resets,linhas_invalidas:d.invalid_lines,
    linhas_longas:d.long_lines,usb_perdidas:d.usb_drops,
    wifi:d.wifi,mqtt:d.mqtt,mqtt_enviadas:d.mqtt_sent,
    mqtt_falhas:d.mqtt_failures,bateria_V:d.battery_V
   },null,2));
 }catch(err){set('state','DESCONECTADO');set('diagnostics',String(err))}
}
refresh();setInterval(refresh,1000);
</script></body></html>
)HTML";
