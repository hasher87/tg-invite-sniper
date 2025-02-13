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
    status_message = None
    for attempt in range(max_retries):
        try:
            # First check if the invite is valid
            try:
                print(f"[+] Checking invite validity: {invite_hash}")
                await client(CheckChatInviteRequest(invite_hash))
                print("[+] Invite is valid")
            except Exception as e:
                error_msg = f"[-] Invalid invite link: {str(e)}"
                print(error_msg)
                return False, error_msg

            # Try to join
            print("[*] Attempting to join...")
            result = await client(ImportChatInviteRequest(invite_hash))
            chat_title = getattr(result.chats[0], 'title', 'Unknown Channel')
            success_msg = f"[+] Successfully joined {chat_title}!"
            print(success_msg)
            return True, success_msg
            
        except UserAlreadyParticipantError:
            msg = "[!] Already a member of this channel"
            print(msg)
            return False, msg
            
        except InviteHashExpiredError:
            msg = "[-] Invite link has expired"
            print(msg)
            return False, msg
            
        except FloodWaitError as e:
            wait_time = e.seconds
            msg = f"[!] Rate limited. Need to wait {wait_time} seconds"
            print(msg)
            if attempt < max_retries - 1:
                await asyncio.sleep(wait_time)
            continue
            
        except Exception as e:
            msg = f"[-] Join attempt {attempt + 1} failed: {str(e)}"
            print(msg)
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
                continue
            return False, msg
    
    return False, "[-] Failed to join after all retries"

async def main():
    try:
        print("[*] Initializing client...")
        
        # Initialize main client with session string
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
            me = await client.get_me()
            user_id = me.id
            print(f"[+] Logged in as: {me.first_name} (ID: {user_id})")
            
            # Get the target channel
            try:
                target = await client.get_entity(TARGET_CHANNEL)
                print(f"[+] Successfully resolved target channel: {getattr(target, 'title', TARGET_CHANNEL)}")
            except ValueError:
                # If direct resolution fails, try searching for it
                print("[*] Direct resolution failed, searching for channel...")
                async for dialog in client.iter_dialogs():
                    if dialog.name == TARGET_CHANNEL or dialog.entity.username == TARGET_CHANNEL.lstrip('@'):
                        target = dialog.entity
                        print(f"[+] Found channel in dialogs: {getattr(target, 'title', TARGET_CHANNEL)}")
                        break
                else:
                    raise ValueError(f"Could not find channel {TARGET_CHANNEL}")
            
            # Send initial status message
            status_msg = (
                f"🎯 **Sniper Active**\n"
                f"📡 Monitoring: `{TARGET_CHANNEL}`\n"
                f"⚡ Status: Active and ready\n"
                f"🔄 Detection rate: ~100ms"
            )
            await client.send_message('me', status_msg, parse_mode='md')
            
        except Exception as e:
            print(f"[-] Failed to setup monitoring: {str(e)}")
            return
        
        # Track statistics
        total_invites = 0
        successful_joins = 0
        failed_joins = 0
        total_detection_time = 0
        
        @client.on(events.NewMessage)
        async def handler(event):
            try:
                # Check if message is from target channel
                if not hasattr(event.message.peer_id, 'channel_id') or event.message.peer_id.channel_id != target.id:
                    return
                    
                nonlocal total_invites, successful_joins, failed_joins, total_detection_time
                detection_start = time.perf_counter()
                text = event.raw_text
                print(f"[*] New message received: {text}")
                
                # Check all invite patterns
                for pattern in INVITE_PATTERNS:
                    if matches := pattern.finditer(text):
                        for match in matches:
                            invite_hash = match.group(1)
                            total_invites += 1
                            
                            detection_time = (time.perf_counter() - detection_start) * 1000
                            total_detection_time += detection_time
                            avg_detection = total_detection_time / total_invites
                            
                            print(f"[+] Found invite: {invite_hash}")
                            
                            # Send detection notification
                            detect_msg = (
                                f"🔍 **Invite Detected**\n"
                                f"⚡ Detection time: `{detection_time:.2f}ms`\n"
                                f"🔗 Link: `t.me/+{invite_hash}`"
                            )
                            await client.send_message('me', detect_msg, parse_mode='md')
                            
                            join_start = time.perf_counter()
                            success, status = await try_join_chat(client, invite_hash)
                            join_time = (time.perf_counter() - join_start) * 1000
                            
                            if success:
                                successful_joins += 1
                                # Send success notification
                                success_msg = (
                                    f"✅ **Join Successful**\n"
                                    f"⚡ Total time: `{(detection_time + join_time):.2f}ms`\n"
                                    f"📊 Stats:\n"
                                    f"- Detection: `{detection_time:.2f}ms`\n"
                                    f"- Join: `{join_time:.2f}ms`\n"
                                    f"📈 Success rate: `{(successful_joins/total_invites)*100:.1f}%`"
                                )
                                await client.send_message('me', success_msg, parse_mode='md')
                            else:
                                failed_joins += 1
                                # Send failure notification
                                fail_msg = (
                                    f"❌ **Join Failed**\n"
                                    f"⚡ Detection time: `{detection_time:.2f}ms`\n"
                                    f"❗ Reason: `{status}`\n"
                                    f"📈 Success rate: `{(successful_joins/total_invites)*100:.1f}%`"
                                )
                                await client.send_message('me', fail_msg, parse_mode='md')
            
            except Exception as e:
                print(f"[-] Error processing message: {str(e)}")
                error_msg = f"⚠️ **Error**: `{str(e)}`"
                await client.send_message('me', error_msg, parse_mode='md')
        
        print("[+] Monitoring for invite links...")
        print("[*] Press Ctrl+C to stop.")
        
        await client.run_until_disconnected()
        
    except Exception as e:
        print(f"[-] Fatal error: {str(e)}")
        if 'client' in locals() and client.is_connected():
            await client.send_message('me', f"🚫 **Fatal Error**: `{str(e)}`", parse_mode='md')
        
if __name__ == '__main__':
    asyncio.run(main())