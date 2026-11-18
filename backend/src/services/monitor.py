import hashlib,json
from datetime import datetime,timezone,timedelta
from fastapi import HTTPException
from sqlalchemy import func,select
from ..config.settings import CONFIG
from ..models.monitor import MonitorModel,MonitorDevice,MonitorBinding,MonitorMessage,MonitorAlarm,MonitorAlarmEvent
from ..utils.serialization import now
from .algorithm import freeze_model,predict_frozen
from .audit import log

MONITOR=CONFIG['monitor']
SEGMENT=timedelta(minutes=MONITOR['segment_window_minutes'])
LATE=timedelta(minutes=MONITOR['late_window_minutes'])
TRIGGER=int(MONITOR['trigger_count'])
NORMAL=MONITOR['normal_label']
REVOKE_REASON=MONITOR['alarm_revoke_reason']
PROCESSED=('accepted','late_accepted')
REJECTED=('rejected','expired')


def parse_time(value):
    try:
        moment=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except (TypeError,ValueError):
        raise HTTPException(422,'事件时间必须为ISO8601时间')
    if moment.tzinfo is None:moment=moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def iso(moment):return moment.astimezone(timezone.utc).isoformat()


def canonical(values):return json.dumps(values,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def _digest(*parts):return hashlib.sha256(canonical(list(parts)).encode()).hexdigest()


def _brief(alarm):
    return {'id':alarm.id,'label':alarm.label,'state':alarm.state,'revision':alarm.revision,'count':alarm.count}


# ---------- frozen models ----------

def _model_row(m):
    return {'id':m.id,'version':m.version_code,'name':m.name,'run_id':m.run_id,'checksum':m.checksum,'run_checksum':m.run_checksum,'training_count':m.training_count,'parameters':m.parameters,'created_by':m.created_by,'created_at':m.created_at}


def list_models(db):return [_model_row(m) for m in db.scalars(select(MonitorModel).order_by(MonitorModel.id))]


def model_or_404(db,id):
    m=db.get(MonitorModel,id)
    if not m:raise HTTPException(404,'未找到模型版本')
    return m


def get_model(db,id):
    m=model_or_404(db,id)
    return {**_model_row(m),'definition':m.model}


def freeze_run_model(db,user,run,version=None):
    from ..models.run import Run
    if not isinstance(run,Run):raise HTTPException(404,'未找到分析任务')
    if run.state!='completed':raise HTTPException(409,'仅已完成的研究可以冻结为连续监测模型')
    if db.scalar(select(MonitorModel.id).where(MonitorModel.run_id==run.id)):raise HTTPException(409,'该研究已冻结过监测模型')
    try:definition=freeze_model(run.snapshot['records'],run.parameters,(run.result or {}).get('checksum',''))
    except ValueError as e:raise HTTPException(422,str(e))
    version=(version or ('M'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')+'-R'+str(run.id))).strip()
    if not 2<=len(version)<=30:raise HTTPException(422,'模型版本号需为2–30字符')
    if db.scalar(select(MonitorModel.id).where(MonitorModel.version_code==version)):raise HTTPException(409,'模型版本号已存在：'+version)
    m=MonitorModel(version_code=version,run_id=run.id,name=run.name,checksum=definition['checksum'],run_checksum=definition['run_checksum'],training_count=definition['training_count'],parameters=run.parameters,model=definition,created_by=user.email,created_at=now())
    db.add(m);db.flush();log(db,user,'monitor.model_frozen',m.id,version+' ← run#'+str(run.id));db.commit()
    return {'id':m.id,'version':m.version_code,'checksum':m.checksum,'training_count':m.training_count,'run_id':m.run_id}


# ---------- devices & bindings ----------

def device_or_404(db,id):
    d=db.get(MonitorDevice,id)
    if not d:raise HTTPException(404,'未找到监测设备')
    return d


def register_device(db,user,data):
    if db.scalar(select(MonitorDevice.id).where(MonitorDevice.key==data.key)):raise HTTPException(409,'设备编号已存在：'+data.key)
    d=MonitorDevice(key=data.key,name=data.name,created_at=now())
    db.add(d);db.flush();log(db,user,'monitor.device_registered',d.id,data.key);db.commit()
    return {'id':d.id,'key':d.key,'name':d.name}


def bindings_for(db,device_id):
    return list(db.scalars(select(MonitorBinding).where(MonitorBinding.device_id==device_id).order_by(MonitorBinding.effective_from)))


def active_binding(bindings,event_time):
    moment=parse_time(event_time);found=None
    for b in bindings:
        if parse_time(b.effective_from)<=moment:found=b
    return found


def list_devices(db):
    models={m.id:m for m in db.scalars(select(MonitorModel))}
    devices=[]
    for d in db.scalars(select(MonitorDevice).order_by(MonitorDevice.key)):
        bindings=bindings_for(db,d.id);current=active_binding(bindings,now())
        devices.append({'id':d.id,'key':d.key,'name':d.name,'active_model':models[current.model_id].version_code if current and current.model_id in models else '','active_since':current.effective_from if current else '','active_alarm_id':db.scalar(select(MonitorAlarm.id).where(MonitorAlarm.device_id==d.id,MonitorAlarm.state=='active')),'active_alarms':db.scalar(select(func.count()).select_from(MonitorAlarm).where(MonitorAlarm.device_id==d.id,MonitorAlarm.state=='active')) or 0,'held_messages':db.scalar(select(func.count()).select_from(MonitorMessage).where(MonitorMessage.device_id==d.id,MonitorMessage.status.in_(('received','late_received')))) or 0,'bindings':[{'model_id':b.model_id,'version':models[b.model_id].version_code if b.model_id in models else '#%d'%b.model_id,'effective_from':b.effective_from,'created_by':b.created_by} for b in bindings]})
    return devices


def bind_model(db,user,device_id,data):
    d=device_or_404(db,device_id);m=model_or_404(db,data.model_id)
    effective=iso(parse_time(data.effective_from))
    if db.scalar(select(MonitorBinding.id).where(MonitorBinding.device_id==d.id,MonitorBinding.effective_from==effective)):raise HTTPException(409,'该设备在此生效时间已绑定模型版本')
    b=MonitorBinding(device_id=d.id,model_id=m.id,effective_from=effective,created_by=user.email,created_at=now())
    db.add(b);db.flush();log(db,user,'monitor.model_bound',b.id,d.key+' → '+m.version_code+' @ '+effective);db.commit()
    # model versions are cut by event time; historical messages are re-judged and
    # already emitted alarms are corrected or revoked with explicit events
    outcome=recover_device(db,user,d.id)
    return {'id':b.id,'device_id':d.id,'model_id':m.id,'version':m.version_code,'effective_from':effective,**outcome}


# ---------- ingest ----------

def _validate_features(values):
    if not isinstance(values,dict):raise HTTPException(422,'声学特征必须为对象')
    out={}
    for key in MONITOR['features']:
        v=values.get(key)
        if isinstance(v,bool) or not isinstance(v,(int,float)):raise HTTPException(422,'声学特征缺失或非数值：'+key)
        v=float(v)
        if v!=v or v in (float('inf'),float('-inf')):raise HTTPException(422,'声学特征必须为有限数值：'+key)
        if v<0:raise HTTPException(422,'声学特征不可为负：'+key)
        out[key]=v
    return out


def _watermark(db,device_id):
    """Latest accepted event time; None until the stream has a first record.

    The watermark only advances on accepted records, so a rejected message can never
    push the late window and a stale retry keeps its original rejection reason.
    """
    latest=db.scalar(select(MonitorMessage.event_time).where(MonitorMessage.device_id==device_id,MonitorMessage.status.notin_(REJECTED),MonitorMessage.event_time!='').order_by(MonitorMessage.event_time.desc()).limit(1))
    return parse_time(latest) if latest else None


def _describe(delta):
    seconds=int(abs(delta.total_seconds()))
    return '%d天%d时%d分'%(seconds//86400,seconds%86400//3600,seconds%3600//60) if seconds>=3600 else '%d分%02d秒'%(seconds//60,seconds%60)


def ingest(db,user,device_id,data,received_at=None):
    """Receive one gateway batch, retrying once if a concurrent batch races.

    The per-device row lock serialises batches on databases that support it; the
    unique (device, message_key) constraint is the final guard. A losing racer rolls
    back and re-evaluates the whole batch in event time, so no judgement is doubled.
    """
    from sqlalchemy.exc import IntegrityError
    try:return _ingest_once(db,user,device_id,data,received_at)
    except IntegrityError:
        db.rollback()
        return _ingest_once(db,user,device_id,data,received_at)


def _ingest_once(db,user,device_id,data,received_at=None):
    # serialise concurrent batches per device; every rule below is evaluated in event
    # time order against the persisted stream, never against arrival order
    device_or_404(db,device_id)
    db.execute(select(MonitorDevice.id).where(MonitorDevice.id==device_id).with_for_update())
    received=parse_time(received_at or now())
    outcome={'accepted':0,'late':0,'held':0,'duplicate':0,'rejected':[],'raised':0,'revoked':0,'corrected':0,'closed':0,'reopened':0}
    prepared=[]
    for item in data.messages:
        key=(item.message_key or '').strip()
        try:
            if not 1<=len(key)<=160:raise HTTPException(422,'报文编号不能为空且最多160字符')
            features=_validate_features(item.features)
            event=parse_time(item.event_time)
            if event>received+timedelta(seconds=30):raise HTTPException(422,'事件时间晚于接收时间，拒绝未来报文')
        except HTTPException as e:
            prepared.append((None,item,None,str(e.detail)))
            continue
        prepared.append((event,item,features,''))
    prepared.sort(key=lambda x:(x[0] or received,x[1].message_key))
    for event,item,features,error in prepared:
        key=item.message_key.strip()
        existing=db.scalar(select(MonitorMessage).where(MonitorMessage.device_id==device_id,MonitorMessage.message_key==key))
        if existing:
            same=existing.features is not None and features is not None and canonical(existing.features)==canonical(features) and event is not None and existing.event_time==iso(event)
            if same:outcome['duplicate']+=1
            else:
                outcome['rejected'].append({'message_key':key,'reason':'重复报文与首次内容不一致，整条拒收'})
                log(db,user,'monitor.rejected',device_id,'重复报文冲突：'+key)
            continue
        def reject(reason,event=event,features=features,status='rejected'):
            db.add(MonitorMessage(device_id=device_id,message_key=key,reference=(item.reference or '')[:120],event_time=iso(event) if event else str(getattr(item,'event_time','') or '')[:40],features=features,status=status,reason=reason,received_at=iso(received)))
            db.flush();outcome['rejected'].append({'message_key':key,'reason':reason})
            log(db,user,'monitor.rejected',device_id,key+'：'+reason)
        if features is None:reject(error);continue
        watermark=_watermark(db,device_id)
        # lateness is measured against the accepted event-time watermark, not arrival
        # delay: a record is late only when the stream has already moved past it
        disorder=(watermark-event) if watermark else timedelta(0)
        if disorder>LATE:
            reject('超过迟到五分钟窗口，拒收留因：比已接收水位线早 '+_describe(disorder),status='expired');continue
        model_id=_resolve_model_id(db,device_id,iso(event))
        status='late_received' if disorder>timedelta(0) else 'received'
        db.add(MonitorMessage(device_id=device_id,message_key=key,reference=(item.reference or '')[:120],event_time=iso(event),features=features,status=status,reason='',received_at=iso(received),late=1 if disorder>timedelta(0) else 0))
        db.flush()
        outcome['late' if disorder>timedelta(0) else 'accepted']+=1
        log(db,user,'monitor.accepted',device_id,key+' @ '+iso(event))
    db.commit()
    healed=recover_device(db,user,device_id)
    for k in ('raised','revoked','corrected','closed','reopened'):outcome[k]=healed[k]
    log(db,user,'monitor.batch_received',device_id,'accepted=%d late=%d held=%d duplicate=%d rejected=%d'%(outcome['accepted'],outcome['late'],outcome['held'],outcome['duplicate'],len(outcome['rejected'])))
    db.commit()
    outcome['held']=db.query(MonitorMessage).filter(MonitorMessage.device_id==device_id,MonitorMessage.status.in_(('received','late_received'))).count()
    outcome['alarms']=[_brief(a) for a in db.scalars(select(MonitorAlarm).where(MonitorAlarm.device_id==device_id).order_by(MonitorAlarm.id))]
    return outcome


def _resolve_model_id(db,device_id,event_time):
    active=active_binding(bindings_for(db,device_id),event_time)
    return active.model_id if active else None


# ---------- judgement ----------

def _judge(db,user,device_id):
    changed=0
    for message in db.scalars(select(MonitorMessage).where(MonitorMessage.device_id==device_id,MonitorMessage.event_time!='',MonitorMessage.status.notin_(REJECTED)).order_by(MonitorMessage.event_time,MonitorMessage.id)):
        model_id=_resolve_model_id(db,device_id,message.event_time)
        if model_id!=message.model_id:
            message.model_id=model_id;message.judged_at='';message.predicted='';message.posterior=None
            if not model_id:
                message.status='late_received' if message.late else 'received';message.reason=''
            elif message.status in ('received','late_received'):
                message.status='accepted' if not message.late else 'late_accepted'
            changed+=1
        if not model_id or message.status in REJECTED or message.judged_at:continue
        label,posterior,_=predict_frozen(db.get(MonitorModel,model_id).model,message.features)
        message.predicted=label;message.posterior=posterior;message.judged_at=now()
        message.status='late_accepted' if message.late else 'accepted';message.reason=''
        changed+=1
    db.commit()
    return changed


# ---------- segmentation ----------

def judged_messages(db,device_id):
    return list(db.scalars(select(MonitorMessage).where(MonitorMessage.device_id==device_id,MonitorMessage.status.in_(PROCESSED),MonitorMessage.judged_at!='').order_by(MonitorMessage.event_time,MonitorMessage.id)))


def episodes(messages):
    """Rebuild fault segments from event-time order.

    A segment is a run of consecutive same-type fault judgements. A normal judgement
    ends the segment; another fault type, a gap longer than the segment window, or a
    model-version boundary also ends it, so a segment never mixes models or bridges an
    idle period. The segment becomes an alarm once three of its records fall inside the
    common ten-minute window; a segment that ended normally stays traceable as a
    closed alarm rather than disappearing.
    """
    runs=[];current=None
    def close(reason):
        nonlocal current
        if current is not None and current['end_reason'] is None:
            current['end_reason']=reason;current['open']=False
        current=None
    for m in messages:
        moment=parse_time(m.event_time)
        if m.predicted==NORMAL:
            close('正常判读结束该段');continue
        if current and current['label']!=m.predicted:close('故障类型变化结束该段')
        if current and current['model_id']!=m.model_id:close('模型版本划界结束该段')
        if current and moment-current['last']>SEGMENT:close('超过十分钟窗口结束该段')
        if current is None:
            current={'label':m.predicted,'model_id':m.model_id,'messages':[],'open':True,'end_reason':None,'last':moment}
            runs.append(current)
        current['messages'].append(m);current['last']=moment
    return runs


def _triggers(messages):
    for i in range(len(messages)-TRIGGER+1):
        window=messages[i:i+TRIGGER]
        if parse_time(window[-1].event_time)-parse_time(window[0].event_time)<=SEGMENT:return True
    return False


def _evidence(run):
    return [{'message_id':m.id,'message_key':m.message_key,'reference':m.reference,'event_time':m.event_time,'received_at':m.received_at,'predicted':m.predicted,'posterior':m.posterior,'features':m.features,'model_id':m.model_id} for m in run['messages']]


def _identity(device_id,model_id,label,anchor):return _digest(device_id,model_id,label,anchor)


def _settle(db,user,device_id):
    from sqlalchemy.exc import IntegrityError
    try:return _settle_once(db,user,device_id)
    except IntegrityError:
        # two concurrent batches for one device can race to raise the same alarm;
        # the identity constraint rejects the loser, which then reconciles again
        db.rollback()
        return _settle_once(db,user,device_id)


def _settle_once(db,user,device_id):
    runs=[r for r in episodes(judged_messages(db,device_id)) if _triggers(r['messages'])]
    alarms=list(db.scalars(select(MonitorAlarm).where(MonitorAlarm.device_id==device_id).order_by(MonitorAlarm.id)))
    by_identity={a.identity:a for a in alarms}
    outcome={'raised':0,'revoked':0,'corrected':0,'closed':0,'reopened':0}
    matched=[]
    for run in runs:
        identity=_identity(device_id,run['model_id'],run['label'],run['messages'][0].message_key)
        alarm=by_identity.get(identity)
        if alarm is None:
            # a late record can move the segment's first message without breaking the
            # segment: adopt the alarm of the same device/type/model that shares any
            # evidence, keeping one alarm identity instead of emitting twice
            keys={m.message_key for m in run['messages']}
            for candidate in alarms:
                if candidate.label!=run['label'] or candidate.model_id!=run['model_id']:continue
                if keys & {e['message_key'] for e in (candidate.evidence or [])}:
                    alarm=candidate;break
        evidence=_evidence(run)
        target='active' if run['open'] else 'closed'
        if alarm is None:
            alarm=MonitorAlarm(device_id=device_id,model_id=run['model_id'],label=run['label'],state=target,revision=1,count=len(evidence),anchor_key=run['messages'][0].message_key,identity=identity,start_event_time=evidence[0]['event_time'],end_event_time=evidence[-1]['event_time'],evidence=evidence,created_at=now(),updated_at=now())
            db.add(alarm);db.flush()
            _emit(db,user,alarm,'raised',1,'',{'label':alarm.label,'model_id':alarm.model_id,'evidence':evidence})
            outcome['raised']+=1
            if target=='closed':
                _emit(db,user,alarm,'closed',1,run['end_reason'] or '',{'evidence':evidence});outcome['closed']+=1
            alarms.append(alarm);by_identity[identity]=alarm;matched.append(alarm)
            continue
        if alarm.identity!=identity:alarm.identity=identity;alarm.anchor_key=run['messages'][0].message_key
        if alarm.state=='revoked' and target=='active':
            alarm.state='active';alarm.revoked_reason='';alarm.revision=int(alarm.revision)+1;alarm.updated_at=now();db.flush()
            _emit(db,user,alarm,'reopened',alarm.revision,'重排后该告警段重新成立',{'evidence':evidence});outcome['reopened']+=1
        elif alarm.state=='active' and target=='closed':
            alarm.state='closed';alarm.revision=int(alarm.revision)+1;alarm.updated_at=now();db.flush()
            _emit(db,user,alarm,'closed',alarm.revision,run['end_reason'] or '正常判读结束该段',{'evidence':evidence});outcome['closed']+=1
        elif alarm.state=='closed' and target=='active':
            # a late record filled an idle gap, so the segment continues instead of
            # ending; the alarm is reopened rather than left closed with a stale end
            alarm.state='active';alarm.revision=int(alarm.revision)+1;alarm.updated_at=now();db.flush()
            _emit(db,user,alarm,'reopened',alarm.revision,'迟到记录补入间隔，该告警段继续',{'evidence':evidence});outcome['reopened']+=1
        if _digest(alarm.label,alarm.model_id,evidence)!=_digest(alarm.label,alarm.model_id,alarm.evidence):
            alarm.revision=int(alarm.revision)+1;alarm.count=len(evidence);alarm.evidence=evidence
            alarm.start_event_time=evidence[0]['event_time'];alarm.end_event_time=evidence[-1]['event_time'];alarm.updated_at=now()
            db.flush()
            _emit(db,user,alarm,'corrected',alarm.revision,'迟到记录重排后更新告警段样本依据',{'evidence':evidence})
            outcome['corrected']+=1
        matched.append(alarm)
    for alarm in alarms:
        if alarm.state in ('active','closed') and alarm not in matched:
            _revoke(db,user,alarm,REVOKE_REASON);outcome['revoked']+=1
    db.commit()
    return outcome


def _emit(db,user,alarm,kind,revision,reason,detail):
    dedupe='a%d|%s|r%d'%(alarm.id,kind,revision)
    if db.scalar(select(MonitorAlarmEvent.id).where(MonitorAlarmEvent.dedupe_key==dedupe)):return
    db.add(MonitorAlarmEvent(alarm_id=alarm.id,device_id=alarm.device_id,kind=kind,revision=revision,dedupe_key=dedupe,reason=reason,detail=detail,created_at=now()))
    db.flush()
    log(db,user,'monitor.alarm.'+kind,alarm.id,alarm.label+' rev'+str(revision)+(('：'+reason) if reason else ''))


def _revoke(db,user,alarm,reason):
    alarm.state='revoked';alarm.revoked_reason=reason;alarm.revision=int(alarm.revision)+1;alarm.updated_at=now()
    db.flush()
    _emit(db,user,alarm,'revoked',alarm.revision,reason,{'label':alarm.label,'model_id':alarm.model_id,'evidence':alarm.evidence})


# ---------- recovery ----------

def recover_device(db,user,device_id):
    changed=_judge(db,user,device_id)
    outcome=_settle(db,user,device_id)
    return {'rejudged':changed,**outcome}


def recover_all(db,user):
    outcome={'rejudged':0,'raised':0,'revoked':0,'corrected':0,'closed':0,'reopened':0,'devices':0}
    for d in db.scalars(select(MonitorDevice).order_by(MonitorDevice.id)):
        result=recover_device(db,user,d.id);outcome['devices']+=1
        for k in ('rejudged','raised','revoked','corrected','closed','reopened'):outcome[k]+=result[k]
    return outcome


# ---------- reading ----------

def _alarm_events(db,alarm_id):
    return [{'id':e.id,'kind':e.kind,'revision':e.revision,'reason':e.reason,'created_at':e.created_at,'detail':e.detail} for e in db.scalars(select(MonitorAlarmEvent).where(MonitorAlarmEvent.alarm_id==alarm_id).order_by(MonitorAlarmEvent.id))]


def _alarm_row(db,a):
    model=db.get(MonitorModel,a.model_id) if a.model_id else None
    device=db.get(MonitorDevice,a.device_id)
    return {'id':a.id,'device_id':a.device_id,'device_key':device.key if device else '','device_name':device.name if device else '','label':a.label,'state':a.state,'revision':a.revision,'count':a.count,'start_event_time':a.start_event_time,'end_event_time':a.end_event_time,'created_at':a.created_at,'updated_at':a.updated_at,'revoked_reason':a.revoked_reason,'model_version':model.version_code if model else '','model_checksum':model.checksum if model else '','model_run_id':model.run_id if model else None,'evidence':a.evidence,'events':_alarm_events(db,a.id)}


def list_alarms(db,device_id=None):
    query=select(MonitorAlarm).order_by(MonitorAlarm.id.desc())
    if device_id:query=select(MonitorAlarm).where(MonitorAlarm.device_id==device_id).order_by(MonitorAlarm.id.desc())
    return [_alarm_row(db,a) for a in db.scalars(query)]


def _message_row(m):
    return {'id':m.id,'device_id':m.device_id,'message_key':m.message_key,'reference':m.reference,'event_time':m.event_time,'received_at':m.received_at,'status':m.status,'reason':m.reason,'predicted':m.predicted,'posterior':m.posterior,'features':m.features,'model_id':m.model_id}


def list_messages(db,device_id=None,status=None,limit=200):
    conditions=[]
    if device_id:
        device_or_404(db,device_id)
        conditions.append(MonitorMessage.device_id==device_id)
    if status:conditions.append(MonitorMessage.status==status)
    query=select(MonitorMessage).where(*conditions).order_by(MonitorMessage.event_time.desc(),MonitorMessage.id.desc()).limit(max(1,min(limit,1000)))
    return [_message_row(m) for m in db.scalars(query)]


def trace(db,alarm_id):
    a=db.get(MonitorAlarm,alarm_id)
    if not a:raise HTTPException(404,'未找到告警')
    row=_alarm_row(db,a)
    model=db.get(MonitorModel,a.model_id) if a.model_id else None
    keys=[e['message_key'] for e in (a.evidence or [])]
    evidence=[_message_row(m) for m in db.scalars(select(MonitorMessage).where(MonitorMessage.device_id==a.device_id).where(MonitorMessage.message_key.in_(keys))) ] if keys else []
    evidence.sort(key=lambda m:(m['event_time'],m['id']))
    row['model']={'id':model.id,'version':model.version_code,'checksum':model.checksum,'run_id':model.run_id,'parameters':model.parameters,'training_count':model.training_count,'created_at':model.created_at,'created_by':model.created_by} if model else None
    row['evidence_messages']=evidence
    return row
