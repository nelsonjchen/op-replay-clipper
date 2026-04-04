# Repo Notes

- The hosted `driver` passenger-hidden path does not require the openpilot UI asset build.
- Keep `OPENPILOT_BUILD_UI_ASSETS=0` by default for the hosted image unless a workflow explicitly needs UI font/raylib assets.
- This was validated on beta version `32c9c63ac100f9fd2e1ba9d92de36a937ef9445276d63eef9c9acdcc9a38c280` with hosted `driver unchanged, passenger hidden` blur smokes on:
  - a public demo route
  - the private passenger route with `COMMA_JWT`
- The no-X hosted path still needs the RF-DETR weights baked into the image if we want to avoid runtime model downloads.
- On Linux/T4 UI debugging, the null-EGL failure was caused by missing NVIDIA GL/EGL userland in the container, not missing Xorg runtime packages. With patched `pyray` present, `renderType=ui` still failed EGL init until `libnvidia-gl-580-server` was added; the same no-X-runtime image then rendered successfully. Treat this as a narrow T4/driver-580 finding until proven on other GPU hosts.
