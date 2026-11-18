from sqlalchemy import Column,Integer,String,Text,JSON,Float,ForeignKey,UniqueConstraint,Index
from ..config.database import Base
from ..config.settings import CONFIG

class MonitorModel(Base):
    __tablename__='monitor_models'
    id=Column(Integer,primary_key=True)
    version_code=Column(String(30),unique=True,nullable=False)
    run_id=Column(Integer,ForeignKey(CONFIG['run_table']+'.id'),unique=True,nullable=False)
    name=Column(String(160),nullable=False)
    checksum=Column(String(64),nullable=False)
    run_checksum=Column(String(64),default='')
    training_count=Column(Integer,nullable=False)
    parameters=Column(JSON,nullable=False)
    model=Column(JSON,nullable=False)
    created_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)

class MonitorDevice(Base):
    __tablename__='monitor_devices'
    id=Column(Integer,primary_key=True)
    key=Column(String(120),unique=True,nullable=False)
    name=Column(String(160),nullable=False)
    created_at=Column(String(40),nullable=False)

class MonitorBinding(Base):
    __tablename__='monitor_bindings'
    __table_args__=(UniqueConstraint('device_id','effective_from',name='uq_monitor_binding_effective'),)
    id=Column(Integer,primary_key=True)
    device_id=Column(Integer,ForeignKey('monitor_devices.id'),nullable=False)
    model_id=Column(Integer,ForeignKey('monitor_models.id'),nullable=False)
    effective_from=Column(String(40),nullable=False)
    created_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)

class MonitorMessage(Base):
    __tablename__='monitor_messages'
    __table_args__=(UniqueConstraint('device_id','message_key',name='uq_monitor_message_key'),Index('ix_monitor_message_device_event','device_id','event_time'))
    id=Column(Integer,primary_key=True)
    device_id=Column(Integer,ForeignKey('monitor_devices.id'),nullable=False)
    message_key=Column(String(160),nullable=False)
    reference=Column(String(120),default='')
    event_time=Column(String(40),default='')
    features=Column(JSON,nullable=True)
    status=Column(String(20),nullable=False,default='held')
    reason=Column(Text,default='')
    received_at=Column(String(40),nullable=False)
    late=Column(Integer,default=0,nullable=False)
    model_id=Column(Integer,ForeignKey('monitor_models.id'),nullable=True)
    predicted=Column(String(120),default='')
    posterior=Column(Float,nullable=True)
    judged_at=Column(String(40),default='')

class MonitorAlarm(Base):
    __tablename__='monitor_alarms'
    __table_args__=(Index('ix_monitor_alarm_device_state','device_id','state'),UniqueConstraint('device_id','identity',name='uq_monitor_alarm_identity'))
    id=Column(Integer,primary_key=True)
    device_id=Column(Integer,ForeignKey('monitor_devices.id'),nullable=False)
    model_id=Column(Integer,ForeignKey('monitor_models.id'),nullable=False)
    label=Column(String(120),nullable=False)
    state=Column(String(20),default='active',nullable=False)
    revision=Column(Integer,default=1,nullable=False)
    count=Column(Integer,nullable=False)
    anchor_key=Column(String(160),nullable=False)
    identity=Column(String(64),nullable=False)
    start_event_time=Column(String(40),nullable=False)
    end_event_time=Column(String(40),nullable=False)
    evidence=Column(JSON,nullable=False)
    created_at=Column(String(40),nullable=False)
    updated_at=Column(String(40),nullable=False)
    revoked_reason=Column(Text,default='')

class MonitorAlarmEvent(Base):
    __tablename__='monitor_alarm_events'
    id=Column(Integer,primary_key=True)
    alarm_id=Column(Integer,ForeignKey('monitor_alarms.id'),nullable=True)
    device_id=Column(Integer,ForeignKey('monitor_devices.id'),nullable=False)
    kind=Column(String(20),nullable=False)
    revision=Column(Integer,nullable=False)
    dedupe_key=Column(String(200),unique=True,nullable=False)
    reason=Column(Text,default='')
    detail=Column(JSON,nullable=True)
    created_at=Column(String(40),nullable=False)
