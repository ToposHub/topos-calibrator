"""
PreflightService - Preflight Check Facade for Backend

This module provides a facade layer that wraps PreflightChecker and
provides Backend-friendly API for pre-flight checks.

Backend integration:
- Backend delegates preflight operations to this service
- Service handles checker initialization and state management
- Backend keeps Qt signals/slots for UI communication
"""

import json
import logging
import threading
from typing import Callable, Dict, List, Optional, Any

from .preflight import PreflightChecker, PreflightReport, PreflightResult, PreflightStatus


logger = logging.getLogger(__name__)


class PreflightService:
    """
    Preflight check facade service
    
    This service wraps PreflightChecker and provides:
    - State management (checker instance, report, override status)
    - Progress callback integration for Qt signals
    - Thread-safe execution
    
    Usage:
        service = PreflightService()
        service.run_checks(
            argyll_bin_path=...,
            display_index=1,
            progress_callback=...,
            completed_callback=...
        )
        report = service.get_report()
    """
    
    def __init__(self):
        """Initialize preflight service"""
        self._checker: Optional[PreflightChecker] = None
        self._report: Optional[PreflightReport] = None
        self._override_enabled: bool = False
        self._completed: bool = False
        self._argyll_bin_path: Optional[str] = None
        self._display_index: int = 1
        self._correction_file_path: Optional[str] = None
        
    # ========== Configuration Methods ==========
    
    def set_argyll_bin_path(self, path: Optional[str]) -> None:
        """Set ArgyllCMS bin directory path"""
        self._argyll_bin_path = path
        if self._checker:
            self._checker.set_argyll_bin_path(path)
    
    def set_display_index(self, index: int) -> None:
        """Set target display index"""
        self._display_index = index
        if self._checker:
            self._checker.set_display_index(index)
    
    def set_correction_file_path(self, path: Optional[str]) -> None:
        """Set correction file path"""
        self._correction_file_path = path
        if self._checker:
            self._checker.set_correction_file_path(path)
    
    def set_override(self, enabled: bool) -> None:
        """Set override status for BLOCK items"""
        self._override_enabled = enabled
        if self._report:
            self._report.update_can_proceed(enabled)
    
    # ========== Checker Initialization ==========
    
    def _init_checker(self) -> PreflightChecker:
        """Initialize checker instance (lazy)"""
        if self._checker is None:
            self._checker = PreflightChecker(
                argyll_bin_path=self._argyll_bin_path,
                display_index=self._display_index,
                correction_file_path=self._correction_file_path,
            )
        return self._checker
    
    # ========== Execution Methods ==========
    
    def run_checks_async(
        self,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        completed_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        error_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """
        Run preflight checks asynchronously in a background thread
        
        Args:
            progress_callback: Called with (current, total, item_id, label)
            completed_callback: Called with report dict on success
            error_callback: Called with error dict on failure
        """
        def run_checks():
            try:
                checker = self._init_checker()
                
                # Update checker parameters
                checker.set_display_index(self._display_index)
                checker.set_correction_file_path(self._correction_file_path)
                
                # Wrap progress callback: 回调在 worker 线程被调用。
                # 不能用 QTimer.singleShot（非 Qt 线程下静默失效），
                # 这里直接调用；回调内部的 Qt 信号 emit 会自动走队列连接回主线程。
                def qt_progress_wrapper(current: int, total: int, item_id: str, label: str):
                    if progress_callback:
                        progress_callback(current, total, item_id, label)
                
                # Run all checks
                report = checker.run_all_checks(progress_callback=qt_progress_wrapper)
                
                # Calculate summary and update can_proceed
                report.calculate_summary()
                report.update_can_proceed(self._override_enabled)
                
                # Store report
                self._report = report
                self._completed = True
                
                # Call completed callback
                if completed_callback:
                    completed_callback(report.to_dict())
                    
            except Exception as e:
                logger.error(f"Preflight check failed: {e}", exc_info=True)
                error_report = {
                    "error": str(e),
                    "can_proceed": False,
                    "results": [],
                    "summary": {"error_count": 1, "total_checks": 0},
                }
                if error_callback:
                    error_callback(error_report)
        
        thread = threading.Thread(target=run_checks, daemon=True)
        thread.start()
    
    def run_checks_sync(
        self,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
    ) -> PreflightReport:
        """
        Run preflight checks synchronously (blocking)
        
        Args:
            progress_callback: Called with (current, total, item_id, label)
            
        Returns:
            PreflightReport: The completed report
        """
        checker = self._init_checker()
        checker.set_display_index(self._display_index)
        checker.set_correction_file_path(self._correction_file_path)
        
        report = checker.run_all_checks(progress_callback=progress_callback)
        report.calculate_summary()
        report.update_can_proceed(self._override_enabled)
        
        self._report = report
        self._completed = True
        
        return report
    
    # ========== Result Access Methods ==========
    
    def get_report(self) -> Optional[PreflightReport]:
        """Get the latest preflight report"""
        return self._report
    
    def get_report_json(self) -> str:
        """Get report as JSON string (for Qt signal emission)"""
        if self._report:
            return self._report.to_json()
        else:
            empty_report = {
                "results": [],
                "summary": {"total_checks": 0},
                "can_proceed": False,
                "message": "尚未执行预检",
            }
            return json.dumps(empty_report)
    
    def can_proceed(self) -> bool:
        """Check if measurement can proceed"""
        if not self._completed:
            return False
        if self._report:
            return self._report.can_proceed
        return False
    
    def has_blocking_items(self) -> bool:
        """Check if there are blocking items"""
        if self._report:
            return len(self._report.get_blocking_items()) > 0
        return False
    
    def get_blocking_items(self) -> List[PreflightResult]:
        """Get list of blocking items"""
        if self._report:
            return self._report.get_blocking_items()
        return []
    
    def get_blocking_items_json(self) -> str:
        """Get blocking items as JSON string"""
        if self._report:
            blocking = self._report.get_blocking_items()
            return json.dumps([r.to_dict() for r in blocking])
        return json.dumps([])
    
    def get_warning_items(self) -> List[PreflightResult]:
        """Get list of warning items"""
        if self._report:
            return self._report.get_warning_items()
        return []
    
    def get_warning_items_json(self) -> str:
        """Get warning items as JSON string"""
        if self._report:
            warnings = self._report.get_warning_items()
            return json.dumps([r.to_dict() for r in warnings])
        return json.dumps([])
    
    def export_report(self, filepath: str) -> bool:
        """Export report to file"""
        if self._report:
            return self._report.export_to_file(filepath)
        return False
    
    # ========== State Query Methods ==========
    
    def is_completed(self) -> bool:
        """Check if preflight has been completed"""
        return self._completed
    
    def is_override_enabled(self) -> bool:
        """Check if override is enabled"""
        return self._override_enabled
    
    def reset(self) -> None:
        """Reset service state"""
        self._report = None
        self._completed = False


__all__ = [
    "PreflightService",
]