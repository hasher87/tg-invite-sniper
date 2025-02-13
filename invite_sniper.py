import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.network.connection import ConnectionTcpAbridged
from telethon.sessions import StringSession
from colorama import Fore, Style
import time

# Load environment variables
load_dotenv()

# Credentials
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
SESSION_STRING = os.getenv('SESSION_STRING')
TARGET_CHANNEL = os.getenv('TARGET_CHANNEL')

# Device Info
DEVICE_MODEL = "Windows 10"
SYSTEM_VERSION = "10.0"
APP_VERSION = "1.0.0"
LANG_CODE = 'en'
SYSTEM_LANG_CODE = 'en'

if not all([API_ID, API_HASH, SESSION_STRING, TARGET_CHANNEL]):
    print("❌ Missing required environment variables")
    exit(1)

# Optimize regex pattern for faster matching
INVITE_PATTERN = re.compile(r't\.me/\+([a-zA-Z0-9_-]+)', re.IGNORECASE | re.ASCII)

async def main():
    try:
        # Initialize client with session string
        client = TelegramClient(
            StringSession(SESSION_STRING),
            API_ID,
            API_HASH,
            device_model=DEVICE_MODEL,
            system_version=SYSTEM_VERSION,
            app_version=APP_VERSION,
            lang_code=LANG_CODE,
            system_lang_code=SYSTEM_LANG_CODE,
            connection=ConnectionTcpAbridged,
            use_ipv6=False,
            connection_retries=1,
            request_retries=1,
            flood_sleep_threshold=0,
            auto_reconnect=True,
            retry_delay=0,
            receive_updates=False,
            catch_up=False,
        )
        
        print(f"🚀 Starting sniper for {TARGET_CHANNEL}...")
        await client.connect()
        
        if not await client.is_user_authorized():
            print("❌ Session is invalid")
            return
            
        print("✅ Connected successfully!")
        
        @client.on(events.NewMessage(chats=TARGET_CHANNEL))
        async def handler(event):
            try:
                detection_time = time.perf_counter()
                text = event.raw_text
                
                if matches := INVITE_PATTERN.finditer(text):
                    for match in matches:
                        invite_hash = match.group(1)
                        try:
                            join_start = time.perf_counter()
                            await asyncio.wait_for(
                                client(ImportChatInviteRequest(invite_hash)),
                                timeout=0.1
                            )
                            join_time = (time.perf_counter() - join_start) * 1000
                            print(f"{Fore.GREEN}✅ {detection_time:.2f}ms/{join_time:.2f}ms | t.me/+{invite_hash}{Style.RESET_ALL}")
                        except Exception as e:
                            print(f"{Fore.RED}❌ Failed to join t.me/+{invite_hash}: {str(e)}{Style.RESET_ALL}")
            
            except Exception as e:
                pass
        
        print("🤖 Monitoring for invite links... Press Ctrl+C to stop.")
        await client.run_until_disconnected()
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        
if __name__ == '__main__':
    asyncio.run(main())