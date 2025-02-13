from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\nHere's your session string, add this to your .env file as SESSION_STRING:\n")
    print(client.session.save())
