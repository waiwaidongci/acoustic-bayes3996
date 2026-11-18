from fastapi import APIRouter,Depends
from ..config.database import db_session
from ..schemas.monitor import FreezeModelInput,DeviceInput,BindingInput,MessageBatch
from ..services.auth import current_user,writer
from ..services import monitor
from ..controllers.monitor import MonitorController as C
router=APIRouter()

@router.get('/monitor/models')
def models(db=Depends(db_session),u=Depends(current_user)):return C.models(db)

@router.get('/monitor/models/{id}')
def model(id:int,db=Depends(db_session),u=Depends(current_user)):return C.model(db,id)

@router.post('/runs/{id}/freeze')
def freeze(id:int,data:FreezeModelInput,db=Depends(db_session),u=Depends(writer)):
    from ..services.runs import get_run
    return C.freeze(db,u,get_run(db,id),data.version)

@router.get('/monitor/devices')
def devices(db=Depends(db_session),u=Depends(current_user)):return C.devices(db)

@router.post('/monitor/devices')
def register(data:DeviceInput,db=Depends(db_session),u=Depends(writer)):return C.register_device(db,u,data)

@router.post('/monitor/devices/{id}/binding')
def bind(id:int,data:BindingInput,db=Depends(db_session),u=Depends(writer)):return C.bind(db,u,id,data)

@router.post('/monitor/devices/{id}/messages')
def messages(id:int,data:MessageBatch,db=Depends(db_session),u=Depends(writer)):return C.ingest(db,u,id,data,data.received_at)

@router.get('/monitor/devices/{id}/messages')
def device_messages(id:int,status:str|None=None,limit:int=200,db=Depends(db_session),u=Depends(current_user)):return C.messages(db,id,status,limit)

@router.get('/monitor/messages')
def all_messages(status:str|None=None,limit:int=200,db=Depends(db_session),u=Depends(current_user)):return C.messages(db,None,status,limit)

@router.get('/monitor/alarms')
def alarms(device_id:int|None=None,db=Depends(db_session),u=Depends(current_user)):return C.alarms(db,device_id)

@router.get('/monitor/alarms/{id}')
def alarm(id:int,db=Depends(db_session),u=Depends(current_user)):return C.trace(db,id)

@router.post('/monitor/recover')
def recover(db=Depends(db_session),u=Depends(writer)):return C.recover(db,u)
