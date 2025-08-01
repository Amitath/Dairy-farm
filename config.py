# config.py
import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # IMPORTANT: Get this from Render's environment variables
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a_very_secret_and_hard_to_guess_key_for_dev'

    # IMPORTANT: Render will provide this URL as an environment variable
    # Default to a local PostgreSQL or comment out if always deploying
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                              'postgresql://dairy_user:your_secure_password@localhost/dairy_db'
                              # ^^^ USE YOUR LOCAL PG CREDS FOR DEV ^^^

    SQLALCHEMY_TRACK_MODIFICATIONS = False