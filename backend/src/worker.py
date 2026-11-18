import json,time,logging,os
from redis import Redis
from sqlalchemy import select
from .config.database import Session
from .config.settings import REDIS_URL,ARTIFACT_DIR
from .models.run import Run
from .models import source,record,user,note,audit,monitor as monitor_models
from .services.algorithm import calculate
from .services.audit import log
from .services.export import csv_response
from .services import monitor as monitor_service
from .config.database import Session as DBSession
queue=Redis.from_url(REDIS_URL)
RECOVERY_EVERY=5.0
last_recovery=0.0
def recover():
    global last_recovery
    try:
        with DBSession() as db:result=monitor_service.recover_all(db,'worker')
        last_recovery=time.time()
        if any(result[k] for k in ('rejudged','raised','revoked','corrected','closed','reopened')):logging.info('monitor recovery %s',result)
    except Exception:logging.exception('monitor recovery failed')
ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
_seeded_monitor=False
def ensure_monitor_seed():
    """First boot order can leave the demo run unfinished when the seed ran.

    The monitoring demo needs a completed research run to freeze, so retry once the
    worker has completed work; the seeding helper itself is idempotent.
    """
    global _seeded_monitor
    if _seeded_monitor or os.getenv('SEED_DEMO','true')!='true':return
    try:
        from scripts.seed_demo import seed_monitor
        with DBSession() as db:
            from .models.monitor import MonitorDevice
            if db.scalar(select(MonitorDevice.id)):_seeded_monitor=True;return
        seeded=seed_monitor()
        _seeded_monitor=bool(seeded)
    except Exception:logging.exception('monitor seed retry failed; will retry')
def execute(id):
    with Session() as db:
        r=db.get(Run,id)
        if not r or r.state!='queued':return
        r.state='running';db.commit()
        try:
            result=calculate(r.snapshot['records'],r.parameters)
            json.dumps(result,allow_nan=False)
            r.result=result;r.state='completed'
            response=csv_response(result,'run.csv')
            (ARTIFACT_DIR/f'run-{r.id}.csv').write_bytes(response.body)
            log(db,'worker','run.completed',r.id)
        except Exception as e:
            logging.exception('analysis failed');r.state='failed';r.error=str(e)[:2000]
            log(db,'worker','run.failed',r.id,r.error)
        db.commit()
def main():
    while True:
        (ARTIFACT_DIR/'heartbeat').write_text(str(time.time()))
        value=queue.blpop('analysis:queue',timeout=2)
        if value:execute(int(value[1]))
        if time.time()-last_recovery>RECOVERY_EVERY:recover()
        ensure_monitor_seed()
if __name__=='__main__':main()
