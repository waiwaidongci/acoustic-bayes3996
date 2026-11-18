import {domain} from '../constants/domain.js';import {research} from '../stores/research.js';import {session} from '../stores/session.js';import {monitorApi} from '../api/research.js';import {runsApi} from '../api/research.js';import {runOptions,metrics} from '../components/common/business.js';import {status} from '../components/common/status.js';import {table} from '../components/common/table.js';import {esc,fmt,localTime,formObject} from '../utils/format.js';import {action,toast,bind} from '../hooks/actions.js';import {eventKinds} from '../constants/enums.js';

const m=domain.monitor;

export const monitor={devices:[],models:[],alarms:[],messages:[],alarmId:null,deviceId:null};

export async function monitorPage(){
  [monitor.devices,monitor.models,monitor.alarms]=await Promise.all([monitorApi.devices(),monitorApi.models(),monitorApi.alarms()]);
  if(!monitor.deviceId||!monitor.devices.some(d=>d.id==monitor.deviceId))monitor.deviceId=monitor.devices.length?monitor.devices[0].id:null;
  if(!monitor.alarmId||!monitor.alarms.some(a=>a.id==monitor.alarmId))monitor.alarmId=monitor.alarms.length?monitor.alarms[0].id:null;
  monitor.messages=monitor.deviceId?await monitorApi.messages(monitor.deviceId):[];
  const trace=monitor.alarmId?await monitorApi.alarm(monitor.alarmId):null;
  const device=monitor.devices.find(d=>d.id==monitor.deviceId);
  const active=monitor.alarms.filter(a=>a.state==='active');const closed=monitor.alarms.filter(a=>a.state==='closed');
  return '<section class="page-heading"><p class="eyebrow">07 / CONTINUOUS WATCH</p><h1>十分钟内连续三次同类故障，才形成一段告警。</h1><p>冻结选定研究的模型版本，按事件时间判读声检报文；单次高后验不直接告警。迟到五分钟内重排并更正，超限拒收留因，跨设备互不影响。</p></section>'
   +metrics([{label:'监测设备',value:monitor.devices.length},{label:'冻结模型版本',value:monitor.models.length},{label:'生效告警段',value:active.length},{label:'已结束告警',value:closed.length},{label:'已撤销告警',value:monitor.alarms.length-active.length-closed.length}])
   +'<div class="split monitor-split"><section>'
   +'<h2>设备与冻结模型 <small>模型换版按事件时间划界，同一段不混模型</small></h2>'
   +deviceTable()+bindings(device)
   +'<h2>本设备报文 <small>按事件时间倒序，保留拒收原因</small></h2>'
   +table(monitor.messages.map(x=>({...x,...(x.features||{}),event_time:localTime(x.event_time),received_at:localTime(x.received_at),posterior:x.posterior==null?'':x.posterior.toFixed(4)})),[{key:'message_key',label:'报文编号'},{key:'event_time',label:'事件时间'},{key:'received_at',label:'接收时间'},{key:'status',label:'状态'},{key:'predicted',label:'判读'},{key:'posterior',label:'最高后验'},{key:'reason',label:'原因'}],{limit:20})
   +'</section><aside>'
   +'<h2>告警段</h2>'+alarmLedger()
   +(session.writable?freezeForm():'<p class="fine">阅读者可追查告警依据；冻结模型与绑定由负责人或分析师执行。</p>')
   +(session.writable&&monitor.devices.length?'<div class="entry-sheet compact-sheet"><h2>现场报文入口</h2><p class="fine">现场网关以 <code>POST /monitor/devices/{id}/messages</code> 报送；下方按钮按当前时间回放一段合成报文，用于演示连续三次判读。</p><button type="button" class="secondary" id="simulate-batch">回放一段演示报文 →</button></div>':'')
   +'<div class="method-note"><b>判读约定</b><p>'+esc(m.segment_window_minutes)+'分钟内连续 '+m.trigger_count+' 次同类故障形成一段告警；正常判读或同类判读中断超过 '+esc(m.segment_window_minutes)+' 分钟即结束该段；迟到 '+esc(m.late_window_minutes)+' 分钟内的记录重排并更正，超限拒收留因；已发出的错误告警以撤销事件补偿。</p></div>'
   +'</aside></div>'
   +(trace?tracePanel(trace):'')
   +(session.writable?deviceForms():'');
}

function deviceTable(){
  return '<div class="ledger monitor-devices">'+monitor.devices.map(d=>'<a href="#monitor" data-device="'+d.id+'" class="'+(d.id==monitor.deviceId?'current':'')+'"><small>'+esc(d.key)+'</small><strong>'+esc(d.name)+'</strong><span>'+esc(d.active_model||'未绑定模型')+'</span><em>'+(d.active_alarms?'生效告警 '+d.active_alarms:'—')+(d.held_messages?' · 暂存 '+d.held_messages:'')+'</em></a>').join('')+'</div>';
}
function bindings(device){
  if(!device)return '';
  return '<p class="file-note">'+esc(device.key)+' · '+esc(device.name)+' · 当前版本 '+esc(device.active_model||'未绑定')+(device.active_since?' · 自 '+esc(localTime(device.active_since)):'')+'</p>'+'<div class="binding-strip">'+(device.bindings.length?device.bindings.map(b=>'<span class="chip">'+esc(b.version)+' <small>自 '+esc(localTime(b.effective_from))+'</small></span>').join(''):'<span class="fine">尚未绑定任何冻结模型。</span>')+'</div>';
}
function alarmLedger(){
  if(!monitor.alarms.length)return '<div class="empty">还没有告警段。连续三次同类故障会在十分钟窗口内形成一段。</div>';
  return '<div class="alarm-ledger">'+monitor.alarms.slice(0,10).map(a=>'<button type="button" class="alarm-row '+(a.id==monitor.alarmId?'current':'')+' '+(a.state==='revoked'?'revoked':'')+'" data-alarm="'+a.id+'"><span class="alarm-type">'+esc(a.device_key)+' · '+esc(a.label)+'</span>'+status(a.state)+'<small>'+a.count+' 条 · 修订 '+a.revision+' · '+esc(a.model_version)+'</small><time>'+esc(localTime(a.start_event_time))+'</time></button>').join('')+'</div>';
}
function tracePanel(trace){
  const model=trace.model;
  return '<section class="trace-panel"><header><div><p class="eyebrow">ALARM TRACE #'+trace.id+'</p><h2>'+esc(trace.device_name)+' · '+esc(trace.label)+'</h2><p class="fine">段起始 '+esc(localTime(trace.start_event_time))+' · 最近 '+esc(localTime(trace.end_event_time))+' · '+trace.count+' 条依据</p></div>'+status(trace.state)+'</header>'
   +(trace.state==='revoked'?'<div class="failure"><b>该告警已撤销</b><p>'+esc(trace.revoked_reason)+'</p><p class="fine">撤销以补偿事件保留，不删除原始告警与样本依据。</p></div>':'')
   +'<div class="trace-grid"><section><h3>样本依据</h3>'+table(trace.evidence_messages.map(e=>({...e,...(e.features||{}),event_time:localTime(e.event_time),received_at:localTime(e.received_at),posterior:e.posterior==null?'':e.posterior.toFixed(4)})),[{key:'message_key',label:'报文编号'},{key:'event_time',label:'事件时间'},{key:'received_at',label:'接收时间'},{key:'status',label:'接收状态'},{key:'predicted',label:'判读'},{key:'posterior',label:'最高后验'},{key:'rms',label:'均方根振幅'},{key:'centroid',label:'频谱质心'},{key:'kurtosis',label:'峭度'}],{limit:50})+'</section>'
   +'<aside><h3>模型版本</h3>'+(model?'<dl class="model-card"><dt>版本</dt><dd>'+esc(model.version)+'</dd><dt>研究任务</dt><dd><a class="text-link" href="#results" data-run="'+model.run_id+'">#'+model.run_id+'</a></dd><dt>训练样本</dt><dd>'+fmt(model.training_count)+'</dd><dt>参数</dt><dd>'+esc(JSON.stringify(model.parameters))+'</dd><dt>冻结校验和</dt><dd><code>'+esc(model.checksum)+'</code></dd></dl>':'<p class="fine">未找到模型。</p>')+'<h3>告警事件</h3><ol class="event-timeline">'+trace.events.map(e=>'<li class="'+esc(e.kind)+'"><b>'+esc(eventKinds[e.kind]||e.kind)+' · 修订 '+e.revision+'</b><time>'+esc(localTime(e.created_at))+'</time>'+(e.reason?'<p>'+esc(e.reason)+'</p>':'')+'</li>').join('')+'</ol></aside></div></section>';
}
function freezeForm(){
  const completed=research.runs.filter(r=>r.state==='completed');
  if(!completed.length)return '';
  return '<div class="entry-sheet compact-sheet"><h2>冻结研究为监测模型</h2><form id="freeze-form"><label>已完成研究<select name="run_id">'+runOptions(completed,research.runId)+'</select></label><label>模型版本号<input name="version" placeholder="留空自动生成" maxlength="30"></label><button type="submit">冻结模型 →</button></form></div>';
}
function deviceForms(){
  return '<div class="split twin-forms"><div class="entry-sheet"><h2>登记监测设备</h2><form id="device-form"><label>设备编号<input name="key" required maxlength="120" placeholder="TX-MOTOR-04"></label><label>设备名称<input name="name" required maxlength="160" placeholder="四号轴流电机"></label><button type="submit">登记设备 →</button></form></div>'
   +'<div class="entry-sheet"><h2>绑定模型版本</h2><form id="binding-form"><label>设备<select name="device_id">'+monitor.devices.map(d=>'<option value="'+d.id+'" '+(d.id==monitor.deviceId?'selected':'')+'>'+esc(d.key)+' · '+esc(d.name)+'</option>').join('')+'</select></label><label>冻结模型<select name="model_id">'+monitor.models.map(x=>'<option value="'+x.id+'">'+esc(x.version)+' · 研究 #'+x.run_id+'</option>').join('')+'</select></label><label>生效事件时间<input name="effective_from" required placeholder="2026-11-18T02:00:00Z"></label><button type="submit">按事件时间绑定 →</button></form></div></div>';
}
function simulationScript(key){
  const base=Date.now()-11*60000,stamp=Date.now();
  const at=minutes=>new Date(base+minutes*60000).toISOString();
  const fault=domain.monitor.signature,normal={rms:domain.sample.rms,centroid:domain.sample.centroid,kurtosis:domain.sample.kurtosis};
  return {messages:[1,3,5,8,10].map((minute,index)=>({message_key:key+'-SIM-'+stamp+'-'+(index+1),reference:'SIM-'+String(index+1).padStart(2,'0'),event_time:at(minute),features:index<4?{...fault}:normal}))};
}

export function bindMonitor(refresh){
  for(const a of document.querySelectorAll('[data-device]'))a.onclick=()=>{monitor.deviceId=Number(a.dataset.device);refresh()};
  for(const b of document.querySelectorAll('[data-alarm]'))b.onclick=()=>{monitor.alarmId=Number(b.dataset.alarm);refresh()};
  const simulate=document.getElementById('simulate-batch');
  if(simulate)simulate.onclick=async()=>{
    const device=monitor.devices.find(d=>d.id==monitor.deviceId);
    if(!device){toast('请先登记监测设备',true);return}
    simulate.disabled=true;
    try{await monitorApi.ingest(device.id,simulationScript(device.key));await refresh();toast('已回放一段合成报文：三次同类故障，正常判读结束该段')}
    catch(error){toast(error.message,true)}
    finally{simulate.disabled=false}
  };
  action('#freeze-form',async form=>{const data=formObject(form);const r=await monitorApi.freeze(Number(data.run_id),data.version.trim());toast('已冻结模型 '+r.version);await refresh()});
  action('#device-form',async form=>{await monitorApi.register(formObject(form));await refresh();toast('监测设备已登记')});
  action('#binding-form',async form=>{const data=formObject(form);const r=await monitorApi.bind(Number(data.device_id),{model_id:Number(data.model_id),effective_from:data.effective_from});await refresh();toast('已按事件时间绑定 '+r.version+(r.revoked?'，撤销 '+r.revoked+' 段告警':''))});
}

