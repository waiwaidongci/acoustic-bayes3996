import {api} from './client.js';
export const sourcesApi={list:()=>api('/sources'),create:data=>api('/sources',{method:'POST',body:JSON.stringify(data)}),update:(id,data)=>api('/sources/'+id,{method:'PUT',body:JSON.stringify(data)}),records:id=>api('/sources/'+id+'/records'),add:(id,records)=>api('/sources/'+id+'/records',{method:'POST',body:JSON.stringify({records})})};
export const runsApi={list:()=>api('/runs'),get:id=>api('/runs/'+id),create:data=>api('/runs',{method:'POST',body:JSON.stringify(data)})};
export const notesApi={list:()=>api('/notes'),create:data=>api('/notes',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/notes/'+id+'/approve',{method:'POST'})};
export const monitorApi={
 models:()=>api('/monitor/models'),
 model:id=>api('/monitor/models/'+id),
 freeze:(runId,version)=>api('/runs/'+runId+'/freeze',{method:'POST',body:JSON.stringify({version:version||null})}),
 devices:()=>api('/monitor/devices'),
 register:data=>api('/monitor/devices',{method:'POST',body:JSON.stringify(data)}),
 bind:(deviceId,data)=>api('/monitor/devices/'+deviceId+'/binding',{method:'POST',body:JSON.stringify(data)}),
 messages:(deviceId,status)=>api('/monitor/devices/'+deviceId+'/messages'+(status?'?status='+status:'')),
 ingest:(deviceId,body)=>api('/monitor/devices/'+deviceId+'/messages',{method:'POST',body:JSON.stringify(body)}),
 alarms:deviceId=>api('/monitor/alarms'+(deviceId?'?device_id='+deviceId:'')),
 alarm:id=>api('/monitor/alarms/'+id),
 recover:()=>api('/monitor/recover',{method:'POST'})
};
