import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon.errors import FloodWaitError, UserAlreadyParticipantError, InviteHashExpiredError
from telethon.network.connection import ConnectionTcpAbridged
from telethon.sessions import StringSession
import time
import sys

# Enable UTF-8 output
if sys.platform.startswith('win'):
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

# Load environment variables
load_dotenv()

# Credentials
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')
SESSION_STRING = os.getenv('SESSION_STRING')
TARGET_CHANNEL = os.getenv('TARGET_CHANNEL')

# Check required variables
if not all([API_ID, API_HASH, SESSION_STRING, TARGET_CHANNEL]):
    print("Error: Missing required environment variables")
    exit(1)

print("Loaded configuration:")
print(f"Target Channel: {TARGET_CHANNEL}")
print(f"Session String Length: {len(SESSION_STRING) if SESSION_STRING else 0}")

# Optimize regex patterns for faster matching
INVITE_PATTERNS = [
    re.compile(r'(?:https?://)?(?:t(?:elegram)?\.me|telegram\.org)/\+([a-zA-Z0-9_-]+)', re.IGNORECASE),
    re.compile(r'(?:https?://)?(?:t(?:elegram)?\.me|telegram\.org)/joinchat/([a-zA-Z0-9_-]+)', re.IGNORECASE),
]

async def try_join_chat(client, invite_hash, max_retries=3):
    """Try to join a chat with retries"""
    for attempt in range(max_retries):
        try:
            # First check if the invite is valid
            try:
                print(f"[+] Checking invite validity: {invite_hash}")
                await client(CheckChatInviteRequest(invite_hash))
                print("[+] Invite is valid")
            except Exception as e:
                print(f"[-] Invalid invite link: {str(e)}")
                return False

            # Try to join
            print("[*] Attempting to join...")
            await client(ImportChatInviteRequest(invite_hash))
            print("[+] Successfully joined!")
            return True
            
        except UserAlreadyParticipantError:
            print("[!] Already a member")
            return False
            
        except InviteHashExpiredError:
            print("[-] Invite expired")
            return False
            
        except FloodWaitError as e:
            wait_time = e.seconds
            print(f"[!] Need to wait {wait_time} seconds")
            if attempt < max_retries - 1:
                await asyncio.sleep(wait_time)
            continue
            
        except Exception as e:
            print(f"[-] Join attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
                continue
            return False
    
    return False

async def main():
    try:
        print("[*] Initializing client...")
        
        # Initialize client with session string
        try:
            session = StringSession(SESSION_STRING)
            print("[+] Session string loaded successfully")
        except Exception as e:
            print(f"[-] Error loading session string: {str(e)}")
            return
            
        client = TelegramClient(
            session,
            API_ID,
            API_HASH,
            device_model="Windows",
            system_version="10",
            app_version="1.0",
            lang_code="en",
            system_lang_code="en",
            connection=ConnectionTcpAbridged,
            use_ipv6=False,
            connection_retries=3,
            auto_reconnect=True,
            retry_delay=1
        )
        
        print("[*] Connecting to Telegram...")
        await client.connect()
        
        if not await client.is_user_authorized():
            print("[-] Session is invalid")
            return
            
        print("[+] Connected successfully!")
        
        # Get entity to ensure we're connected to the right channel
        try:
            target = await client.get_entity(TARGET_CHANNEL)
            print(f"[+] Successfully resolved target channel: {getattr(target, 'title', TARGET_CHANNEL)}")
        except Exception as e:
            print(f"[-] Failed to resolve target channel: {str(e)}")
            return
        
        @client.on(events.NewMessage(chats=target))
        async def handler(event):
            try:
                detection_time = time.perf_counter()
                text = event.raw_text
                print(f"[*] New message received: {text}")
                
                # Check all invite patterns
                for pattern in INVITE_PATTERNS:
                    if matches := pattern.finditer(text):
                        for match in matches:
                            invite_hash = match.group(1)
                            print(f"[+] Found invite: {invite_hash}")
                            
                            join_start = time.perf_counter()
                            success = await try_join_chat(client, invite_hash)
                            join_time = (time.perf_counter() - join_start) * 1000
                            
                            if success:
                                print(f"[+] Joined in {join_time:.2f}ms | Detection: {detection_time:.2f}ms")
            
            except Exception as e:
                print(f"[-] Error processing message: {str(e)}")
        
        print("[+] Monitoring for invite links...")
        print("[*] Press Ctrl+C to stop.")
        
        await client.run_until_disconnected()
        
    except Exception as e:
        print(f"[-] Fatal error: {str(e)}")
        
if __name__ == '__main__':
    asyncio.run(main())