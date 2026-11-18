import json,random,logging
from datetime import datetime,timezone
from sqlalchemy import select,func
from src.config.database import Base,engine,Session
from src.config.settings import CONFIG
from src.models.user import User
from src.models.source import Source
from src.models.record import Record
from src.models.run import Run
from src.models import note,audit,monitor
from src.models.monitor import MonitorDevice,MonitorMessage,MonitorAlarm
from src.utils.security import hash_password
from src.utils.serialization import now
from src.services.runs import queue
from src.services.domain_validation import validate_record

def seed_values(kind,index,batch,rng):
    if kind=='gaussian':
        cls=index%3;return {'rms':round(max(.1,rng.gauss([1.2,3.0,2.0][cls]+batch*.08,.35)),3),'centroid':round(max(100,rng.gauss([900,1600,2300][cls],170)),2),'kurtosis':round(max(.1,rng.gauss([2.8,5.2,3.9][cls],.45)),3),'label':['正常','轴承磨损','转子偏心'][cls]}
    if kind=='density':
        cls=index%3
        if index%19==0:return {'temperature':round(rng.uniform(12,42),2),'humidity':round(rng.uniform(12,92),2),'particles':round(rng.uniform(4,140),2)}
        return {'temperature':round(rng.gauss([19,26,32][cls]+batch*.3,.8),2),'humidity':round(rng.gauss([72,45,28][cls],2.5),2),'particles':round(max(.1,rng.gauss([22,48,85][cls],3)),2)}
    if kind=='transition':
        choices=[['序章','材料','工艺','案例'],['序章','案例','附录'],['材料','工艺','案例','附录'],['序章','材料','案例'],['序章']]
        path=choices[rng.randrange(len(choices))];return {'session':f'SY-{batch+1}-{index+1:04}','path':'>'.join(path)}
    if kind=='forest':
        moisture=rng.uniform(20,60);thickness=rng.uniform(1,8);temperature=rng.uniform(50,100);airflow=rng.uniform(1,5)
        minutes=12+1.6*moisture+8*thickness-.45*temperature-3*airflow+0.1*moisture*thickness+rng.gauss(0,3)
        return {'moisture':round(moisture,2),'thickness':round(thickness,2),'temperature':round(temperature,2),'airflow':round(airflow,2),'minutes':round(max(5,minutes),2)}
    if kind=='neighbors':
        uid=index//6;slot=index%6;exhibit=(uid%3*3+slot)%12
        return {'visitor':f'V{uid+1:03}','exhibit':f'E{exhibit+1:02}','rating':round(max(1,min(5,3+(1 if exhibit%3==uid%3 else -.4)+rng.gauss(0,.55))),1)}

MONITOR_DEVICES=[('TX-MOTOR-01','一号轴流电机'),('TX-MOTOR-02','二号轴流电机'),('TX-PUMP-03','三号循环泵')]
MONITOR_LINES={
    'TX-MOTOR-01':[('01-00','2026-11-17T01:00:00Z',{'rms':1.2,'centroid':900,'kurtosis':2.8}),
                   ('01-01','2026-11-17T01:03:00Z',{'rms':3.0,'centroid':1600,'kurtosis':5.2}),
                   ('01-02','2026-11-17T01:06:00Z',{'rms':3.0,'centroid':1600,'kurtosis':5.2}),
                   ('01-03','2026-11-17T01:09:00Z',{'rms':3.0,'centroid':1600,'kurtosis':5.2}),
                   ('01-04','2026-11-17T01:12:00Z',{'rms':3.0,'centroid':1600,'kurtosis':5.2})],
    'TX-MOTOR-02':[('02-01','2026-11-17T01:02:00Z',{'rms':2.0,'centroid':2300,'kurtosis':3.9}),
                   ('02-02','2026-11-17T01:05:00Z',{'rms':2.0,'centroid':2300,'kurtosis':3.9}),
                   ('02-03','2026-11-17T01:08:00Z',{'rms':2.0,'centroid':2300,'kurtosis':3.9})],
    'TX-PUMP-03':[('03-01','2026-11-17T01:00:00Z',{'rms':1.2,'centroid':900,'kurtosis':2.8}),
                   ('03-02','2026-11-17T01:03:00Z',{'rms':3.0,'centroid':1600,'kurtosis':5.2}),
                   ('03-03','2026-11-17T01:05:00Z',{'rms':3.0,'centroid':1600,'kurtosis':5.2}),
                   ('03-04','2026-11-17T01:07:00Z',{'rms':3.0,'centroid':1600,'kurtosis':5.2}),
                   ('03-05','2026-11-17T01:09:00Z',{'rms':1.2,'centroid':900,'kurtosis':2.8})],
}

def seed_monitor():
    """Freeze the newest completed research and replay a short device stream.

    The replay exercises the monitoring rules end to end: one active alarm, one alarm
    corrected by a late record, one alarm revoked by a late normal record, and one
    rejected stale record. Devices are only created once, so repeated calls or a
    restart never duplicates or rewrites operator decisions.
    """
    from src.models.monitor import MonitorModel,MonitorDevice,MonitorBinding,MonitorMessage
    from src.services import monitor as ms
    from src.schemas.monitor import MessageBatch
    with Session() as db:
        if db.scalar(select(MonitorDevice.id)):return None
        run=db.scalar(select(Run).where(Run.state=='completed').order_by(Run.id))
        if not run:return None
        admin=db.scalar(select(User).where(User.role=='admin'))
        model=db.scalar(select(MonitorModel).where(MonitorModel.run_id==run.id))
        if not model:
            frozen=ms.freeze_run_model(db,admin,run,'M-202611-01')
            model=db.get(MonitorModel,frozen['id'])
        devices={}
        for key,name in MONITOR_DEVICES:
            d=MonitorDevice(key=key,name=name,created_at=now());db.add(d);db.flush()
            devices[key]=d
            db.add(MonitorBinding(device_id=d.id,model_id=model.id,effective_from='2026-11-01T00:00:00+00:00',created_by=admin.email,created_at=now()))
        db.commit()
        for key,lines in MONITOR_LINES.items():
            d=devices[key]
            for suffix,event,features in lines:
                db.add(MonitorMessage(device_id=d.id,message_key=key+'-'+suffix,reference='SEQ-'+suffix,event_time=event,features=features,status='received',reason='',received_at=event))
            db.commit()
            ms.recover_device(db,admin,d.id)
        late=[('TX-MOTOR-01',[('01-05','2026-11-17T01:10:00Z',{'rms':3.0,'centroid':1600,'kurtosis':5.2})],'2026-11-17T01:13:00Z'),
              ('TX-MOTOR-02',[('02-04','2026-11-17T01:06:00Z',{'rms':1.2,'centroid':900,'kurtosis':2.8})],'2026-11-17T01:10:00Z'),
              ('TX-PUMP-03',[('03-99','2026-11-17T00:30:00Z',{'rms':3.0,'centroid':1600,'kurtosis':5.2})],'2026-11-17T01:20:00Z')]
        for key,items,received in late:
            d=devices[key]
            messages=[{'message_key':key+'-'+suffix,'reference':'SEQ-'+suffix,'event_time':event,'features':features} for suffix,event,features in items]
            ms.ingest(db,admin,d.id,MessageBatch(messages=messages),received)
        return {'devices':len(devices)}

def counts(db):
    return {cls.__tablename__:db.scalar(select(func.count()).select_from(cls)) for cls in (User,Source,Record,Run,MonitorDevice,MonitorMessage,MonitorAlarm)}
def seed():
    Base.metadata.create_all(engine);rng=random.Random(42);queued=[]
    with Session() as db:
        for role in ('admin','analyst','viewer'):
            email=role+'@'+CONFIG['slug']+'.demo'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,password_hash=hash_password('Research2026!'),role=role))
        for batch in range(3):
            key=CONFIG['code']+f'-202611-{batch+1:02}'
            source=db.scalar(select(Source).where(Source.key==key))
            if not source:
                source=Source(key=key,name=key+' '+['秋季常规组','复测对照组','工艺观察组'][batch],filename=CONFIG['slug']+f'-202611-{batch+1:02}.csv',description=CONFIG['scenario']);db.add(source);db.flush()
            for index in range(CONFIG['seed_count']):
                reference=key+f'-{index+1:04}'
                vals=seed_values(CONFIG['algorithm'],index,batch,rng)
                if not db.scalar(select(Record.id).where(Record.source_id==source.id,Record.reference==reference)):
                    db.add(Record(source_id=source.id,reference=reference,values=validate_record(vals)))
            db.flush()
            if batch==0 and not db.scalar(select(Run.id).where(Run.name=='首轮种子研究')):
                records=[{'id':r.id,'source_id':r.source_id,'reference':r.reference,'values':r.values} for r in db.scalars(select(Record).where(Record.source_id==source.id).order_by(Record.id))]
                run=Run(source_id=source.id,name='首轮种子研究',state='queued',parameters=CONFIG['default_parameters'],snapshot={'source':{'id':source.id,'name':source.name,'filename':source.filename},'records':records},created_at=now());db.add(run);db.flush();queued.append(run.id)
        db.commit();print(json.dumps(counts(db),ensure_ascii=False))
    try:seed_monitor()
    except Exception:logging.exception('monitor seed skipped')
    for id in queued:
        try:queue.rpush('analysis:queue',id)
        except Exception:logging.exception('seed queue unavailable')
if __name__=='__main__':seed()
