"""Lazy access to window_shell module globals that tests patch at runtime."""


def project_root():
    from portman.gui import window_shell
    return window_shell.PROJECT_ROOT


def webengine_available():
    from portman.gui import window_shell
    return window_shell.HAS_WEBENGINE