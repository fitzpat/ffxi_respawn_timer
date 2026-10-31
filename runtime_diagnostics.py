"""Local callback errors and stack traces when the Tk event loop stops responding."""
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import tempfile
import threading
import time


class RuntimeDiagnostics:
    def __init__(self, root, directory, stall_seconds=5):
        self.root = root
        self.stall_seconds = stall_seconds
        self.last_heartbeat = time.monotonic()
        self._stop = threading.Event()
        self._heartbeat_id = None
        self.logger = logging.Logger('ffxi_respawn_timer')
        self.path = Path(directory) / 'mob_timer_diagnostics.log'
        try:
            handler = RotatingFileHandler(self.path, maxBytes=1024 * 1024,
                                          backupCount=2, encoding='utf-8')
        except OSError:
            self.path = Path(tempfile.gettempdir()) / 'mob_timer_diagnostics.log'
            handler = RotatingFileHandler(self.path, maxBytes=1024 * 1024,
                                          backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        self.logger.addHandler(handler)
        self.handler = handler
        self._old_callback = root.report_callback_exception
        self._old_thread_hook = threading.excepthook
        root.report_callback_exception = self.report_callback_exception
        threading.excepthook = self.report_thread_exception
        self.logger.info('Application started; pid=%s', os.getpid())
        self._heartbeat()
        self._thread = threading.Thread(target=self._watch, name='UI diagnostics', daemon=True)
        self._thread.start()

    def report_callback_exception(self, exc_type, value, traceback):
        self.logger.error('UI callback failed', exc_info=(exc_type, value, traceback))

    def report_thread_exception(self, args):
        self.logger.error('Background thread failed: %s', args.thread.name,
                          exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    def _heartbeat(self):
        self.last_heartbeat = time.monotonic()
        if not self._stop.is_set():
            self._heartbeat_id = self.root.after(1000, self._heartbeat)

    def _watch(self):
        stalled = False
        while not self._stop.wait(1):
            delay = time.monotonic() - self.last_heartbeat
            if delay >= self.stall_seconds and not stalled:
                self.logger.error('UI heartbeat stalled for %.1f seconds; dumping thread stacks', delay)
                self.handler.acquire()
                try:
                    faulthandler.dump_traceback(file=self.handler.stream, all_threads=True)
                    self.handler.flush()
                except (OSError, RuntimeError):
                    self.logger.exception('Could not capture stalled thread stacks')
                finally:
                    self.handler.release()
                stalled = True
            elif delay < self.stall_seconds and stalled:
                self.logger.info('UI heartbeat resumed')
                stalled = False

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)
        try:
            if self._heartbeat_id:
                self.root.after_cancel(self._heartbeat_id)
        except Exception:
            pass  # The Tk interpreter may already have been destroyed.
        self.root.report_callback_exception = self._old_callback
        threading.excepthook = self._old_thread_hook
        self.logger.info('Application closed')
        self.handler.close()
        self.logger.removeHandler(self.handler)
