# -*- coding: utf-8 -*-
from typing import Callable, Optional

class Logger:
    _instance = None
    
    def __init__(self):
        self._callback: Optional[Callable[[str, str], None]] = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_callback(self, callback: Callable[[str, str], None]):
        """
        Callback signature: (message: str, level: str) -> None
        Level: 'info', 'warn', 'error'
        """
        self._callback = callback

    def log(self, message: str, level: str = 'info'):
        if self._callback:
             # Schedule connection to UI thread if needed (handled by UI side callback usually)
             self._callback(message, level)
        else:
            print(f"[{level.upper()}] {message}")

    def info(self, msg): self.log(msg, 'info')
    def warn(self, msg): self.log(msg, 'warn')
    def error(self, msg): self.log(msg, 'error')
