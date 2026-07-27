"""
Application factory for HandBrake TSD Helper.

This file:
- Creates the Flask app
- Loads preset config + saved jobs
- Starts the dispatcher thread
- Registers all HTTP routes
"""

import os

from flask import Flask

# Import initialization functions
from .presets import load_preset_config
from .jobs import initialize_jobs_system


def create_app():
    """
    Flask application factory.

    Called by:
      - __main__.py when running container
      - WSGI servers (gunicorn, uvicorn, etc)

    Returns:
        Flask app instance
    """
    app = Flask(__name__)
    development = os.environ.get("FLASK_DEBUG") == "1" or os.environ.get("FLASK_ENV") == "development"
    app.config["TEMPLATES_AUTO_RELOAD"] = development
    app.jinja_env.auto_reload = development

    # 1️⃣ Load preset configuration into memory
    load_preset_config()

    # 2️⃣ Restore job queue + start dispatcher
    initialize_jobs_system()

    # 3️⃣ Register routes (import inside function to avoid circular deps)
    from .routes import register_routes
    register_routes(app)

    return app
