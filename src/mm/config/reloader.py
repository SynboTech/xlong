from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from mm.config.change_audit import ConfigChangeReport, diff_settings
from mm.config.settings import AppSettings


@dataclass(frozen=True)
class ReloadResult:
    changed: bool
    settings: Optional[AppSettings]
    message: str
    change_report: Optional[ConfigChangeReport] = None


class ConfigReloader:
    def __init__(self, path: str) -> None:
        self.path = path
        self._last_mtime: Optional[float] = None
        self._last_settings: Optional[AppSettings] = None

    def check(self) -> ReloadResult:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError as exc:
            return ReloadResult(False, None, "config stat failed: {0}".format(exc))
        if self._last_mtime is None:
            self._last_mtime = mtime
            try:
                self._last_settings = AppSettings.from_file(self.path)
            except Exception:
                self._last_settings = None
            return ReloadResult(False, None, "initial config mtime recorded")
        if mtime == self._last_mtime:
            return ReloadResult(False, None, "config unchanged")
        self._last_mtime = mtime
        try:
            settings = AppSettings.from_file(self.path)
            report = diff_settings(self._last_settings, settings) if self._last_settings is not None else None
            self._last_settings = settings
            return ReloadResult(True, settings, "config reloaded", report)
        except Exception as exc:
            return ReloadResult(True, None, "config reload failed: {0}".format(exc))
