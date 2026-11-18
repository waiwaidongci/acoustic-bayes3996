from pydantic import BaseModel,Field
from typing import Any

class FreezeModelInput(BaseModel):
    version:str|None=Field(default=None,max_length=30)

class DeviceInput(BaseModel):
    key:str=Field(min_length=1,max_length=120)
    name:str=Field(min_length=2,max_length=160)

class BindingInput(BaseModel):
    model_id:int
    effective_from:str=Field(min_length=1,max_length=40)

class MessageInput(BaseModel):
    message_key:str
    reference:str=Field(default='',max_length=120)
    event_time:str
    features:dict[str,Any]

class MessageBatch(BaseModel):
    messages:list[MessageInput]=Field(min_length=1,max_length=500)
    received_at:str|None=None
