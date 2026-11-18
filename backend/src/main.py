import os,logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from .config.database import Base,engine
from .config.settings import CONFIG
from .models import user,source,record,run,note,audit,monitor as monitor_models
from .middlewares.errors import error_boundary
from .middlewares.rate_limit import rate_limit
from .routes import auth,sources,runs,notes,audit as audit_routes,monitor as monitor_routes
from .services.runs import queue


def _recover_pending():
    """Finish judgements and alarm reconciliation interrupted by a restart.

    Receiving, judging and alarm writes are separate commits; this pass only reads
    persisted state, so re-running it is safe and cannot duplicate an alarm event.
    """
    from .config.database import Session
    from .services import monitor
    try:
        with Session() as db:monitor.recover_all(db,'system')
    except Exception:logging.exception('monitor recovery failed; service remains available')


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    _recover_pending()
    if os.getenv('SEED_DEMO','true')=='true':
        try:
            from scripts.seed_demo import seed
            seed()
        except Exception:logging.exception('seed failed; service remains available')
    yield
app=FastAPI(title=CONFIG['title'],lifespan=lifespan)
app.middleware('http')(error_boundary)
app.middleware('http')(rate_limit)
for router in (auth.router,sources.router,runs.router,notes.router,audit_routes.router,monitor_routes.router):app.include_router(router)
@app.get('/health')
def health():
    with engine.connect() as c:c.execute(text('SELECT 1'))
    queue.ping();return {'status':'ok'}
@app.get('/catalog')
def catalog():return CONFIG
