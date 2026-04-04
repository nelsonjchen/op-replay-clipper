# Repo Notes

- The hosted `driver` passenger-hidden path does not require the openpilot UI asset build.
- Keep `OPENPILOT_BUILD_UI_ASSETS=0` by default for the hosted image unless a workflow explicitly needs UI font/raylib assets.
- This was validated on beta version `32c9c63ac100f9fd2e1ba9d92de36a937ef9445276d63eef9c9acdcc9a38c280` with hosted `driver unchanged, passenger hidden` blur smokes on:
  - a public demo route
  - the private passenger route with `COMMA_JWT`
- The no-X hosted path still needs the RF-DETR weights baked into the image if we want to avoid runtime model downloads.
