"""Qt bridge for a cancellable, spawn-safe worker process."""
import multiprocessing
import threading
from PySide6.QtCore import QThread, Signal
from transcription_job import run_job


class Transcriber(QThread):
    completed = Signal(list)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(str, int)

    def __init__(self, path, model_name, allow_download=False, audio_index=0, target=run_job, options=None):
        super().__init__()
        self.path, self.model_name = path, model_name
        self.allow_download, self.audio_index = allow_download, audio_index
        self.target = target
        self.options = options
        self.cancel_requested = threading.Event()
        self.process = None

    def cancel(self):
        self.cancel_requested.set()

    def run(self):
        reader = writer = process = None
        terminal = None
        try:
            if self.cancel_requested.is_set():
                self.cancelled.emit()
                return
            context = multiprocessing.get_context('spawn')
            reader, writer = context.Pipe(duplex=False)
            process = context.Process(target=self.target, args=(writer, self.path, self.model_name, self.allow_download, self.audio_index, self.options), daemon=True)
            self.process = process
            process.start()
            writer.close()
            while not self.cancel_requested.is_set():
                if reader.poll(0.05):
                    try:
                        message = reader.recv()
                    except EOFError:
                        break
                    if message[0] == 'progress':
                        self.progress.emit(message[1], message[2])
                    else:
                        terminal = message
                        break
                elif not process.is_alive():
                    break
        except Exception as exc:
            terminal = ('failed', str(exc))
        finally:
            # Reap only our isolated child. Never terminate the Qt thread.
            if process is not None and process.pid is not None:
                if self.cancel_requested.is_set() or terminal is None:
                    if process.is_alive():
                        process.terminate()
                process.join(2)
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            if reader is not None:
                reader.close()
            if writer is not None:
                writer.close()
            self.process = None
        if self.cancel_requested.is_set():
            self.cancelled.emit()
        elif terminal and terminal[0] == 'completed':
            self.completed.emit(terminal[1])
        else:
            self.failed.emit(terminal[1] if terminal else 'The transcription process exited unexpectedly. Retry the job.')
