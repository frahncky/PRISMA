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
nav{display:flex;gap:10px;margin:18px 0;flex-wrap:wrap}
button{min-height:50px;padding:10px 22px;font-size:16px;border-radius:10px;border:1px solid #3d5b74;color:#e9f5fb;background:#152b41;cursor:pointer;touch-action:manipulation}
button[aria-selected="true"]{background:#076b85;border-color:#35cce7}
button:disabled{opacity:.5;cursor:default}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.card{border:1px solid #284359;border-radius:14px;padding:20px;background:#132638}
.card h2{margin:0 0 14px;font-size:17px;color:#b0c4d2}
.value{font-size:clamp(25px,4.5vw,42px);font-weight:750;color:#fff}
.unit{font-size:15px;color:#94adbd}
small{display:block;margin-top:12px;color:#a9c1cc;line-height:1.6}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.6}
label{display:block;margin:12px 0 6px;color:#b0c4d2}
input{width:100%;min-height:46px;font-size:16px;padding:8px 10px;border-radius:8px;border:1px solid #3d5b74;background:#0d1d2d;color:#e9f5fb}
progress{width:100%;height:18px;margin-top:14px}
#freq{margin-top:14px}
[hidden]{display:none!important}.warning{margin-top:16px;color:#ffc87d}
@media(max-width:700px){body{padding:14px}.grid{grid-template-columns:1fr}h1{font-size:24px}}
</style></head><body><main>
<header><div><h1>◈ PRISMA</h1><p>Interface touch de monitoramento • DEMOEM → ESP32-S3</p></div><div id="state">Conectando…</div></header>
<nav aria-label="Navegação"><button id="measureBtn" aria-selected="true" onclick="tab('measure')">Medições</button>
<button id="networkBtn" aria-selected="false" onclick="tab('network')">Dispositivo e IoT</button>
<button id="otaBtn" aria-selected="false" onclick="tab('ota')">Atualizar DEMOEM</button></nav>
<section id="measure">
<div class="grid">
<article class="card"><h2>Fase A</h2><div class="value" id="va">—</div><span class="unit vunit">V RMS</span><small id="ia">Corrente: —</small><small id="pa">Potência ativa: —</small></article>
<article class="card"><h2>Fase B</h2><div class="value" id="vb">—</div><span class="unit vunit">V RMS</span><small id="ib">Corrente: —</small><small id="pb">Potência ativa: —</small></article>
<article class="card"><h2>Fase C</h2><div class="value" id="vc">—</div><span class="unit vunit">V RMS</span><small id="ic">Corrente: —</small><small id="pc">Potência ativa: —</small></article>
</div>
<article class="card" id="freq"><h2>Frequência</h2><div class="value" id="f">—</div><span class="unit">Hz (ciclos inteiros da fase A)</span></article>
<p class="warning">Valores de uma janela de ~1 s calculados no ESP a partir das somas da placa. Não são medições certificadas. Sem ganhos de calibração, saem em contagens do ADC.</p>
</section>
<section id="network" hidden><article class="card"><h2>Diagnóstico</h2><pre id="diagnostics">Aguardando dados…</pre></article>
<p class="warning">A leitura HTTP não possui autenticação: use apenas em rede local isolada e confiável. MQTT exige TLS e certificado CA.</p></section>
<section id="ota" hidden><article class="card"><h2>Firmware da DEMOEM pelo bootloader PRISMA</h2>
<p id="otaInfo">Consultando…</p>
<label for="file">Aplicação (S19 do projeto EM256 App)</label><input id="file" type="file" accept=".s19,.S19,.srec,.mot">
<label for="token">Token de atualização</label><input id="token" type="password" autocomplete="off">
<p><button id="send" onclick="upload()">Gravar na DEMOEM</button></p>
<progress id="bar" max="1" value="0"></progress><pre id="otaState"></pre></article>
<p class="warning">A placa só roda a nova aplicação depois que o próprio bootloader confere o CRC-32. Se algo falhar no meio, ela fica no bootloader: basta enviar de novo.</p></section>
</main><script>
const tabs=['measure','network','ota'];
function tab(which){
 tabs.forEach(t=>{document.getElementById(t).hidden=t!==which;
  document.getElementById(t+'Btn').setAttribute('aria-selected',String(t===which))});
 if(which==='ota')otaRefresh();
}
function set(id,value){document.getElementById(id).textContent=value}
function fmt(value,digits=1){return typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits):'—'}
async function refresh(){
 try{
  const res=await fetch('/api/status',{cache:'no-store'});
  if(!res.ok)throw Error('HTTP '+res.status);
  const d=await res.json(),fresh=d.fresh===true,counts=d.v_unit!=='V';
  set('state',d.ota_busy?'ATUALIZANDO A DEMOEM':(fresh?'MEDINDO':'SEM RESUMOS RECENTES'));
  document.querySelectorAll('.vunit').forEach(e=>e.textContent=counts?'contagens RMS':'V RMS');
  const iu=d.i_unit==='A'?' A':' contagens',pu=d.p_unit==='W'?' W':' contagens²';
  ['a','b','c'].forEach((phase,j)=>{
   set('v'+phase,fresh?fmt(d.vrms?.[j],counts?0:1):'—');
   set('i'+phase,fresh&&d.irms?'Corrente: '+fmt(d.irms[j],d.i_unit==='A'?2:0)+iu:'Corrente: indisponível');
   set('p'+phase,fresh&&d.p?'Potência ativa: '+fmt(d.p[j],d.p_unit==='W'?1:0)+pu:'Potência ativa: indisponível');
  });
  set('f',fresh?fmt(d.f_Hz,3):'—');
  set('diagnostics',JSON.stringify({
    dispositivo:d.device_id,origem:d.source,janela:d.seq,idade_ms:d.age_ms,
    resumos:d.summaries,janelas_perdidas:d.lost_windows,rajadas:d.bursts,respostas:d.replies,
    quadros:d.frames,erros_crc:d.crc_errors,cabecalhos_invalidos:d.bad_headers,linhas_longas:d.long_lines,
    usb_bytes_perdidos:d.usb_drop_bytes,usb_para_placa_bytes:d.usb_to_board_bytes,
    mensagem_da_placa:d.board_message,uart_tx:d.uart_tx,atualizacao:d.ota_enabled,
    wifi:d.wifi,mqtt:d.mqtt,mqtt_enviadas:d.mqtt_sent,mqtt_falhas:d.mqtt_failures,bateria_V:d.battery_V
   },null,2));
 }catch(err){set('state','DESCONECTADO');set('diagnostics',String(err))}
}
let otaTimer=null;
async function otaRefresh(){
 try{
  const o=await (await fetch('/api/ota',{cache:'no-store'})).json();
  set('otaInfo',o.enabled?'Atualização habilitada neste gateway.':'Atualização desligada: defina PRISMA_OTA_TOKEN e os pinos TX/RX da UART.');
  document.getElementById('send').disabled=!o.enabled||o.state==='flashing';
  const bar=document.getElementById('bar');bar.max=o.total||1;bar.value=o.state==='done'?bar.max:o.done;
  set('otaState',o.state==='idle'?'':`${o.state} ${o.stage} ${o.done}/${o.total}\n${o.message}`+
   (o.image_bytes?`\nimagem: ${o.image_bytes} bytes, CRC-32 0x${(o.image_crc32>>>0).toString(16).toUpperCase().padStart(8,'0')}`:'')+
   (o.resends?`\nreenvios: ${o.resends}`:''));
  clearTimeout(otaTimer);
  if(o.state==='flashing'||o.state==='receiving')otaTimer=setTimeout(otaRefresh,500);
 }catch(err){set('otaState',String(err))}
}
async function upload(){
 const file=document.getElementById('file').files[0];
 if(!file){set('otaState','Escolha o arquivo S19.');return}
 const form=new FormData();form.append('image',file,file.name);
 set('otaState','Enviando…');
 try{
  const res=await fetch('/api/ota',{method:'POST',body:form,headers:{'X-Prisma-Token':document.getElementById('token').value}});
  set('otaState',await res.text());
 }catch(err){set('otaState',String(err))}
 otaRefresh();
}
refresh();setInterval(refresh,1000);
</script></body></html>
)HTML";
