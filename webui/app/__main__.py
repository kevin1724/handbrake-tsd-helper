"""
Entry point for running the HandBrake TSD Helper Web UI as:

    python -m webui

This just:
- Creates the Flask app using the factory in __init__.py
- Starts the dev server (inside Docker you'll normally rely on gunicorn
  or just `python -m webui` as the container CMD).
"""

from . import create_app


def main():
    # Create the Flask app
    app = create_app()

    # Run the built-in Flask server
    # In Docker you'll expose port 8080 → 8080
    app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
