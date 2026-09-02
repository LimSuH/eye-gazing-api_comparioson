"""Local fault reports, without recording webcam frames or calibration samples."""
from datetime import datetime, timezone
import faulthandler
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
from threading import Lock


class RuntimeDiagnostics:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = Lock()
        self.current = {}
        self.logger = logging.Logger('gaze-runtime')
        self.handler = None
        self.fault_file = None
        self.write_warning = False

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(self.directory/'runtime.log',
                                          maxBytes=2*1024*1024, backupCount=1,
                                          encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        self.logger.addHandler(self.handler)
        previous = self.directory/'last_operation.json'
        if previous.exists():
            previous.replace(self.directory/'last_operation.previous.json')
        try:
            fault_path = self.directory/'native_fault.log'
            if fault_path.exists() and fault_path.stat().st_size > 2*1024*1024:
                fault_path.replace(self.directory/'native_fault.previous.log')
            self.fault_file = fault_path.open('ab', buffering=0)
            self.fault_file.write(f'\nSession {datetime.now(timezone.utc).isoformat()} PID={os.getpid()}\n'.encode())
            # Keep this descriptor open until disable(), including during shutdown.
            faulthandler.enable(file=self.fault_file, all_threads=True)
        except Exception:
            if self.fault_file:
                self.fault_file.close()
                self.fault_file = None
            self.logger.warning('Native fault handler unavailable', exc_info=True)
        self.logger.info('Server process starting; no webcam data is recorded in diagnostic logs')
        self._update(state='idle', stage='server.start', engine=None, endpoint=None, frame_seq=None)
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.logger.error('Server stopped with an exception', exc_info=(exc_type, exc, tb))
        self.logger.info('Server process stopped')
        if self.fault_file is not None:
            faulthandler.cancel_dump_traceback_later()
            faulthandler.disable()
            self.fault_file.close()
            self.fault_file = None
        if self.handler is not None:
            self.logger.removeHandler(self.handler)
            self.handler.close()
            self.handler = None

    def _update(self, **changes):
        with self.lock:
            self.current.update(changes)
            self.current.update(time_utc=datetime.now(timezone.utc).isoformat(), pid=os.getpid())
            try:
                # Bounded record of the last operation, flushed before native calls.
                # Atomic replacement keeps readers from seeing half-written JSON.
                temporary = self.directory/'last_operation.tmp'
                temporary.write_text(json.dumps(self.current, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
                temporary.replace(self.directory/'last_operation.json')
            except OSError:
                if not self.write_warning:
                    self.write_warning = True
                    self.logger.warning('Cannot update last_operation.json; tracking may continue', exc_info=True)

    def begin(self, endpoint, frame_seq=None):
        # Deliberately accept no request body, token, image, or gaze coordinates.
        if endpoint not in ('/api/start', '/api/frame', '/api/finish', '/api/end'):
            endpoint = 'unknown'
        if type(frame_seq) is not int or not 0 <= frame_seq <= 2**53-1:
            frame_seq = None
        self._update(endpoint=endpoint, frame_seq=frame_seq, state='busy', stage='request', engine=None)
        if self.fault_file is not None:
            # A hang may never throw a Python exception. Dump once, without
            # terminating the process or interrupting/calibrating any model.
            faulthandler.dump_traceback_later(60, repeat=False, file=self.fault_file, exit=False)

    def stage(self, name, engine=None):
        if name not in ('frame.decode', 'engine.initialize', 'engine.process',
                        'engine.fit', 'reference.initialize', 'reference.capture',
                        'reference.observe', 'session.close', 'response.encode'):
            raise ValueError('Unknown diagnostic stage')
        if engine not in (None, 'eyetrax', 'gazefollower', 'eyegestures', 'webgazer'):
            raise ValueError('Unknown diagnostic engine')
        self._update(stage=name, engine=engine)

    def complete(self):
        if self.fault_file is not None:
            faulthandler.cancel_dump_traceback_later()
        self._update(state='processed')

    def transfer(self, endpoint, frame_seq, outcome, status, size, *, error=False):
        # A successful socket write is NOT an acknowledgement from the browser.
        # Only fixed route/sequence/status fields are logged; no response content.
        if endpoint not in ('/api/frame', '/api/frame-result'):
            return
        if type(frame_seq) is not int or not 0 <= frame_seq <= 2**53-1:
            frame_seq = None
        self.logger.log(logging.WARNING if error else logging.INFO,
                        'HTTP transfer path=%s frame_seq=%s outcome=%s status=%s bytes=%s',
                        endpoint, frame_seq, outcome, status, size, exc_info=error)

    def failed(self):
        # Call inside an except block; traceback omits local variables and images.
        if self.fault_file is not None:
            faulthandler.cancel_dump_traceback_later()
        self._update(state='failed')
        self.logger.exception('Request failed at %s', self.snapshot())

    def snapshot(self):
        with self.lock:
            return dict(self.current)
