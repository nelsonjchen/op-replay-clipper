# Repo Notes

- The hosted `driver` passenger-hidden path does not require the openpilot UI asset build.
- The all-in-one hosted image should keep `OPENPILOT_BUILD_UI_ASSETS=1` by default so `ui` and `ui-alt` install the patched null-EGL `raylib` into the openpilot venv that `big_ui_engine.py` actually uses.
- This was validated on beta version `32c9c63ac100f9fd2e1ba9d92de36a937ef9445276d63eef9c9acdcc9a38c280` with hosted `driver unchanged, passenger hidden` blur smokes on:
  - a public demo route
  - the private passenger route with `COMMA_JWT`
- The no-X hosted path still needs the RF-DETR weights baked into the image if we want to avoid runtime model downloads.
- On Linux/T4 UI debugging, the null-EGL failure had two causes: missing NVIDIA GL/EGL userland in the container, and the patched `raylib` initially being installed into the wrong Python env. The working recipe was:
  - keep Xorg runtime packages optional/off
  - install `libnvidia-gl-580-server`
  - build UI assets
  - install the patched null-EGL `raylib-python-cffi` into `/home/batman/openpilot/.venv`
  - then `renderType=ui` succeeds locally on the T4 VM
Treat this as a narrow T4/driver-580 finding until proven on other GPU hosts.
