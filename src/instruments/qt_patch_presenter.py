"""
QtPatchPresenter - Wraps PatchWindow as PatchPresenter implementation.

This adapter enables the MeasurementService to work with PyQt-based
patch display through the standard PatchPresenter interface.

Thread Safety:
    PyQt operations must happen on the main thread. This presenter
    should only be used from the Qt main thread.

Reference:
- src/patch_window.py (wrapped implementation)
- src/instruments/base.py (interface definition)
"""

import logging
import time
from typing import Optional

from PyQt6.QtCore import QTimer

from .base import (
    PatchPresenter,
    PatchDisplayError,
)


logger = logging.getLogger(__name__)


class PyQtPatchPresenter(PatchPresenter):
    """
    Adapter that wraps PatchWindow as PatchPresenter.

    This class translates between the MeasurementService's abstract
    interface and PatchWindow's concrete PyQt implementation.

    Key features:
    - Full screen color patch display
    - OLED window mode support (10%/18% window patches)
    - Black frame insertion for OLED measurements
    - Direct color drawing to bypass color management

    Example:
        >>> from src.patch_window import PatchWindow
        >>> window = PatchWindow()
        >>> presenter = PyQtPatchPresenter(window, display_id=0)
        >>> presenter.show_rgb(255, 0, 0)  # Show red patch
        >>> presenter.hide()  # Hide patch
    """

    def __init__(
        self,
        patch_window: 'PatchWindow',
        display_id: int = 0,
        oled_window_percent: float = 100.0
    ):
        """
        Initialize presenter with existing PatchWindow.

        Args:
            patch_window: PatchWindow instance to wrap
            display_id: Target display ID/index
            oled_window_percent: Initial OLED window size (default 100%)
        """
        self._patch_window = patch_window
        self._display_id = display_id
        self._oled_window_percent = oled_window_percent
        self._black_frame_duration_ms = 100
        self._current_rgb = (0, 0, 0)

    def show_rgb(self, r: int, g: int, b: int) -> None:
        """
        Display a color patch with given RGB values.

        Args:
            r: Red value (0-255)
            g: Green value (0-255)
            b: Blue value (0-255)

        Raises:
            PatchDisplayError: If display fails
        """
        try:
            self._current_rgb = (r, g, b)

            if self._patch_window:
                # Set OLED window size if configured
                if self._oled_window_percent < 100.0:
                    self._set_oled_window_mode()

                self._patch_window.set_color(r, g, b)

                # Show window if hidden
                if not self._patch_window.isVisible():
                    self._patch_window.show_fullscreen()

        except Exception as e:
            raise PatchDisplayError(
                message=f"Failed to display patch: {e}",
                display_id=self._display_id,
                rgb_requested=(r, g, b)
            )

    def hide(self) -> None:
        """Hide/clear the color patch display."""
        try:
            if self._patch_window:
                self._patch_window.hide_patch()
            self._current_rgb = (0, 0, 0)
        except Exception as e:
            logger.error(f"Failed to hide patch: {e}")

    def target_display_id(self) -> int:
        """Return target display ID."""
        return self._display_id

    def set_oled_window_size(self, percent: float) -> None:
        """
        Set window size percentage for OLED displays.

        Args:
            percent: Window size as percentage of display (10.0, 18.0, etc.)
        """
        self._oled_window_percent = percent
        if self._patch_window:
            self._set_oled_window_mode()

    def _set_oled_window_mode(self) -> None:
        """Configure OLED window mode on PatchWindow."""
        # Note: PatchWindow needs to implement OLED window mode
        # This is a placeholder that logs the configuration
        if self._oled_window_percent < 100.0:
            logger.debug(
                f"OLED window mode: {self._oled_window_percent}% "
                f"(centered patch, black surround)"
            )
            # TODO: Implement actual OLED window mode in PatchWindow
            # The window should show a small centered patch with
            # the rest of the screen black

    def show_black_frame(self, duration_ms: int = 100) -> None:
        """
        Display a black frame for OLED BFI (Black Frame Insertion).

        This shows a black patch for the specified duration, then
        returns to the previous color. Used to reset OLED pixel
        states between high-brightness measurements.

        Args:
            duration_ms: Duration of black frame in milliseconds

        Note:
            This implementation uses QTimer for timing. The caller
            should wait for the black frame to complete before
            proceeding with measurement.
        """
        try:
            if self._patch_window:
                # Store current color
                previous_rgb = self._current_rgb

                # Show black
                self._patch_window.set_color(0, 0, 0)
                self._current_rgb = (0, 0, 0)

                # Schedule return to previous color
                if duration_ms > 0:
                    QTimer.singleShot(
                        duration_ms,
                        lambda: self._restore_color(previous_rgb)
                    )

                logger.debug(f"Black frame shown for {duration_ms}ms")

        except Exception as e:
            logger.error(f"Failed to show black frame: {e}")

    def _restore_color(self, rgb: tuple) -> None:
        """Restore previous color after black frame."""
        try:
            if self._patch_window and rgb != (0, 0, 0):
                self._patch_window.set_color(rgb[0], rgb[1], rgb[2])
                self._current_rgb = rgb
        except Exception as e:
            logger.error(f"Failed to restore color: {e}")

    def show_fullscreen(self) -> None:
        """Show patch window in fullscreen mode."""
        try:
            if self._patch_window:
                self._patch_window.show_fullscreen()
        except Exception as e:
            raise PatchDisplayError(
                message=f"Failed to show fullscreen: {e}",
                display_id=self._display_id
            )

    def show_resizable(self, width: int = 400, height: int = 400) -> None:
        """Show patch window as resizable window."""
        try:
            if self._patch_window:
                self._patch_window.show_resizable(width, height)
        except Exception as e:
            raise PatchDisplayError(
                message=f"Failed to show resizable window: {e}",
                display_id=self._display_id
            )

    @property
    def current_rgb(self) -> tuple:
        """Get current RGB being displayed."""
        return self._current_rgb

    @property
    def is_visible(self) -> bool:
        """Check if patch window is visible."""
        return self._patch_window is not None and self._patch_window.isVisible()

    @property
    def oled_window_percent(self) -> float:
        """Get current OLED window size."""
        return self._oled_window_percent

    def start_guardian(self, interval_ms: int = 2000) -> None:
        """Start window on-top guardian timer."""
        if self._patch_window:
            self._patch_window.start_guardian(interval_ms)

    def stop_guardian(self) -> None:
        """Stop window on-top guardian timer."""
        if self._patch_window:
            self._patch_window.stop_guardian()


class WebUIPatchPresenter(PatchPresenter):
    """
    Adapter for displaying patches via Web UI (QWebChannel).

    This presenter sends color changes to the web-based UI through
    Backend signals, useful when using system ICC (no LUT clearing).

    Example:
        >>> presenter = WebUIPatchPresenter(backend, display_id=0)
        >>> presenter.show_rgb(255, 0, 0)  # Sends signal to web UI
    """

    def __init__(
        self,
        backend: 'Backend',
        display_id: int = 0
    ):
        """
        Initialize presenter with Backend reference.

        Args:
            backend: Backend instance for sending signals
            display_id: Target display ID
        """
        self._backend = backend
        self._display_id = display_id
        self._current_rgb = (0, 0, 0)

    def show_rgb(self, r: int, g: int, b: int) -> None:
        """
        Display a color patch via web UI signal.

        Args:
            r: Red value (0-255)
            g: Green value (0-255)
            b: Blue value (0-255)

        Raises:
            PatchDisplayError: If signal sending fails
        """
        try:
            self._current_rgb = (r, g, b)
            # Backend._show_color handles both web UI and patch window
            self._backend._show_color(r, g, b)
        except Exception as e:
            raise PatchDisplayError(
                message=f"Failed to send patch to web UI: {e}",
                display_id=self._display_id,
                rgb_requested=(r, g, b)
            )

    def hide(self) -> None:
        """Hide/clear the color patch display."""
        try:
            self._backend._show_color(0, 0, 0)
            self._current_rgb = (0, 0, 0)
        except Exception as e:
            logger.error(f"Failed to hide web UI patch: {e}")

    def target_display_id(self) -> int:
        """Return target display ID."""
        return self._display_id

    def set_oled_window_size(self, percent: float) -> None:
        """
        Set window size percentage for OLED displays.

        Note: Web UI presenter doesn't support OLED window mode.
        This is a no-op placeholder.
        """
        logger.warning(
            "WebUIPatchPresenter does not support OLED window mode. "
            "Use PyQtPatchPresenter for OLED measurements."
        )

    def show_black_frame(self, duration_ms: int = 100) -> None:
        """
        Display a black frame for OLED BFI.

        Note: This is a simple implementation that just shows black.
        No timing is handled - caller should manage timing.
        """
        self.show_rgb(0, 0, 0)

    @property
    def current_rgb(self) -> tuple:
        """Get current RGB being displayed."""
        return self._current_rgb