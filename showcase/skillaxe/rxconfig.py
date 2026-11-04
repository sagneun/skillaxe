import reflex as rx
from reflex.plugins.sitemap import SitemapPlugin

config = rx.Config(app_name='dashboard', backend_host='127.0.0.1', frontend_port=3000, backend_port=8000, telemetry_enabled=False, disable_plugins=[SitemapPlugin])
