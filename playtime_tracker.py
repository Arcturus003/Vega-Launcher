from PySide6.QtCore import QThread, Signal
import time

class PlaytimeTrackerThread(QThread):
    tracking_finished = Signal(str, int) # pid, elapsed_seconds
    
    def __init__(self, process, pid):
        super().__init__()
        self.process = process
        self.pid = str(pid)
        self.exit_code = 0
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        start_time = time.time()
        while self._is_running:
            if self.process is None or not hasattr(self.process, "poll"):
                break
            try:
                rc = self.process.poll()
                if rc is not None:
                    self.exit_code = rc
                    break
            except (OSError, ValueError, AttributeError, Exception):
                break
            time.sleep(0.5)
        end_time = time.time()

        elapsed = max(0, int(end_time - start_time))
        self.tracking_finished.emit(self.pid, elapsed)
