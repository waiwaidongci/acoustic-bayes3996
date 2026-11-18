from ..services import monitor

class MonitorController:
    models=staticmethod(monitor.list_models)
    model=staticmethod(monitor.get_model)
    freeze=staticmethod(monitor.freeze_run_model)
    devices=staticmethod(monitor.list_devices)
    register_device=staticmethod(monitor.register_device)
    bind=staticmethod(monitor.bind_model)
    ingest=staticmethod(monitor.ingest)
    messages=staticmethod(monitor.list_messages)
    alarms=staticmethod(monitor.list_alarms)
    trace=staticmethod(monitor.trace)
    recover=staticmethod(monitor.recover_all)
