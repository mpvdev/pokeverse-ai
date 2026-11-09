"""The served application: loads a local ``.env`` (real environment variables win), then builds."""

from dotenv import find_dotenv, load_dotenv

from pokeverse.api.app import create_app

load_dotenv(find_dotenv(usecwd=True))
app = create_app()
