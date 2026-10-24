from PySide6.QtCore import QThread, Signal
from runtime_provisioner import RuntimeProvisioner, RuntimeSpec, DEFAULT_PROVISIONER


class DownloadVanillaThread(QThread):
    task_finished = Signal(bool, str)
    progress_update = Signal(str)
    progress_val = Signal(int)
    progress = Signal(int)
    status = Signal(str)
    finished_dl = Signal(bool, str)

    def __init__(self, version_id, minecraft_dir, provisioner: RuntimeProvisioner = None, lang: str = "tr"):
        super().__init__()
        self.version_id = version_id
        self.minecraft_dir = minecraft_dir
        self.provisioner = provisioner or DEFAULT_PROVISIONER
        self.lang = lang
        self._is_cancelled = False
        self.progress_val.connect(self.progress.emit)
        self.progress_update.connect(self.status.emit)
        self.task_finished.connect(self.finished_dl.emit)


    def cancel(self):
        self._is_cancelled = True

    def run(self):
        en = self.lang == "en"
        cancel_msg = "Download cancelled by user." if en else "İndirme kullanıcı tarafından iptal edildi."
        try:
            if self._is_cancelled:
                self.task_finished.emit(False, cancel_msg)
                return

            def on_progress(cur, tot, text):
                if cur > 0:
                    self.progress_val.emit(cur)
                if text:
                    self.progress_update.emit(text)

            spec = RuntimeSpec(mc_version=self.version_id, loader="vanilla")
            self.provisioner.install_client_runtime(
                spec,
                mc_dir=self.minecraft_dir,
                on_progress=on_progress,
                is_cancelled=lambda: self._is_cancelled,
                lang=self.lang,
            )
            if self._is_cancelled:
                self.task_finished.emit(False, cancel_msg)
            else:
                self.task_finished.emit(True, "Installation successful." if en else "Kurulum başarılı.")
        except Exception as e:
            self.task_finished.emit(False, str(e))
