"""Is the user in a full-screen app (game, video, presentation)? Uses Windows' own 'user is busy' signal
(SHQueryUserNotificationState), the same one apps use to hold back notifications, so it is right for games,
F11 browsers and PowerPoint slide shows without guessing from window sizes."""
from __future__ import annotations

import ctypes

QUNS_BUSY = 2                     # a full-screen app is running
QUNS_RUNNING_D3D_FULL_SCREEN = 3  # a game in exclusive full-screen mode
QUNS_PRESENTATION_MODE = 4        # presentation settings are on
_BUSY_STATES = (QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE)


def foreground_is_fullscreen() -> bool:
    try:
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:   # S_OK == 0
            return False
        return state.value in _BUSY_STATES
    except Exception:
        return False                                        # when unsure, stay active
