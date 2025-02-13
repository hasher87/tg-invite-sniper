import os
import re
import asyncio
import uuid
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.qrlogin import QRLogin
from colorama import Fore, Style
import subprocess
import time
import qrcode
from io import BytesIO
import base64
from collections import OrderedDict
import sys

# Load environment variables
load_dotenv()

# Bot credentials
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')

# Store user states and sessions
user_states = {}
user_processes = {}
flood_wait_until = None

ACCESS_CODE = "hilmiisawesome"

class UserState:
    def __init__(self):
        self.waiting_for_access_code = True
        self.waiting_for_qr_scan = False
        self.waiting_for_channel = False
        self.sniper_running = False
        self.client = None
        self.qr_login = None
        self.qr_message_id = None
        self.session_string = None
        self.process = None
        self.sniper_id = None
        self.target_channel = None
        self.start_time = None

async def generate_qr(url):
    """Generate QR code image from URL"""
    try:
        # Create QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save to bytes
        bio = BytesIO()
        img.save(bio, format='PNG')
        bio.seek(0)
        
        return bio
    except Exception as e:
        print(f"Error generating QR code: {str(e)}")
        raise

async def start_sniper(session_string, target_channel, chat_id):
    """Start a new sniper process"""
    try:
        # Create a unique ID for this sniper instance
        sniper_id = str(uuid.uuid4())
        
        # Create a fresh environment dictionary
        env = {}
        
        # Add only required variables
        env.update({
            'API_ID': str(API_ID),
            'API_HASH': str(API_HASH),
            'SESSION_STRING': session_string,
            'TARGET_CHANNEL': str(target_channel),
            'SNIPER_ID': str(sniper_id),
            'NOTIFICATION_CHAT_ID': str(chat_id),
            'BOT_TOKEN': str(BOT_TOKEN)
        })
        
        print("Starting sniper with configuration:")
        print(f"Target Channel: {env['TARGET_CHANNEL']}")
        print(f"Session String Length: {len(env['SESSION_STRING'])}")
        print(f"Notification Chat ID: {env['NOTIFICATION_CHAT_ID']}")
        
        # Start the sniper process with the clean environment
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            'invite_sniper.py',
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd()
        )
        
        # Start output reader tasks
        asyncio.create_task(read_output(process.stdout, "STDOUT"))
        asyncio.create_task(read_output(process.stderr, "STDERR"))
        
        print(f"Started sniper process {sniper_id} for channel {target_channel}")
        
        # Update user state with target channel and start time
        if chat_id in user_states:
            user_states[chat_id].target_channel = target_channel
            user_states[chat_id].start_time = datetime.now()
        
        return process, sniper_id
        
    except Exception as e:
        print(f"Error starting sniper: {str(e)}")
        print(f"Error details: {repr(e)}")
        raise

async def read_output(pipe, name):
    """Read output from a subprocess pipe"""
    while True:
        line = await pipe.readline()
        if not line:
            break
        try:
            print(f"[{name}] {line.decode().strip()}")
        except Exception as e:
            print(f"Error reading {name}: {str(e)}")

async def check_qr_login(bot, chat_id, user_id, state):
    """Check QR login status periodically"""
    try:
        while state.waiting_for_qr_scan:
            try:
                # Check if QR code was accepted
                result = await state.qr_login.wait(10)  # Wait for 10 seconds
                if result:
                    # QR code accepted, get the session string
                    state.session_string = state.client.session.save()
                    print(f"QR login successful for user {user_id}")
                    print(f"Session string length: {len(state.session_string)}")
                    
                    # Clear states
                    state.waiting_for_qr_scan = False
                    state.waiting_for_access_code = False
                    
                    # Update QR message
                    await bot.edit_message(
                        chat_id,
                        state.qr_message_id,
                        "✅ Login successful! Now please send me the channel username to monitor (e.g. @channel)"
                    )
                    
                    # Set state for channel input
                    state.waiting_for_channel = True
                    break
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"Error checking QR login: {str(e)}")
                await bot.send_message(
                    chat_id,
                    "❌ Error during login. Please use /start to try again."
                )
                state.waiting_for_qr_scan = False
                break
                
    except Exception as e:
        print(f"Error in QR login check: {str(e)}")
        state.waiting_for_qr_scan = False

async def main():
    try:
        print("🚀 Starting bot...")
        
        # Initialize bot client with persistent session
        bot = TelegramClient(
            "bot.session",  # Persistent session file
            API_ID,
            API_HASH
        )
        
        try:
            await bot.start(bot_token=BOT_TOKEN)
            print("✅ Bot started successfully!")
        except FloodWaitError as e:
            wait_time = e.seconds
            wait_until = datetime.now() + timedelta(seconds=wait_time)
            print(f"⚠️ Need to wait {wait_time} seconds due to flood control.")
            print(f"Please try again after {wait_until.strftime('%H:%M:%S')}")
            return
            
        @bot.on(events.NewMessage(pattern='/start'))
        async def start_command(event):
            user_id = event.sender_id
            
            # Reset user state
            user_states[user_id] = UserState()
            
            # Create welcome buttons
            buttons = [
                [Button.inline("📖 FAQ", b"faq")],
                [Button.inline("⚠️ Disclaimer", b"disclaimer")]
            ]
            
            # Send banner image with welcome message
            await bot.send_file(
                event.chat_id,
                'sniper.png',
                caption=(
                    "🎯 Welcome to Telegram Invite Sniper Pro! 🚀\n\n"
                    "🔥 Features:\n"
                    "• Ultra-fast invite detection\n"
                    "• Optimized joining algorithm\n"
                    "• Multi-channel monitoring\n"
                    "• Real-time performance stats\n\n"
                    "⚡️ Average Join Speed: 100-300ms\n\n"
                    "🔒 This is a private bot. Please enter your access code to continue.\n\n"
                    "❓ Need an access code?\n"
                    "Contact @0xDeepSeek on Twitter (x.com/0xDeepSeek)"
                ),
                buttons=buttons
            )

        @bot.on(events.NewMessage(pattern='/confirm'))
        async def confirm_login(event):
            user_id = event.sender_id
            if user_id not in user_states:
                await event.respond("⚠️ Please start over with /start")
                return
                
            state = user_states[user_id]
            if not state.waiting_for_qr_scan:
                await event.respond("⚠️ This command is only valid during QR login.")
                return
                
            try:
                print(f"Manual confirmation requested by user {user_id}")
                print(f"Client state: {state.client}")
                
                # Try to connect the client first
                if not state.client.is_connected():
                    print("Client not connected, attempting to connect...")
                    await state.client.connect()
                
                # Check authorization
                print("Checking authorization status...")
                is_authorized = await state.client.is_user_authorized()
                print(f"Authorization status: {is_authorized}")
                
                if is_authorized:
                    print("User is authorized via manual confirmation!")
                    state.session_string = state.client.session.save()
                    state.waiting_for_qr_scan = False
                    state.waiting_for_access_code = False
                    
                    await event.respond(
                        "✅ Successfully logged in!\n\n"
                        "🎯 Now, please enter the target channel username (e.g., @channel)\n\n"
                        "ℹ️ Make sure you've already joined the channel you want to monitor."
                    )
                else:
                    print("Authorization check failed")
                    # Try to get the QR login status
                    if state.qr_login:
                        try:
                            status = await state.qr_login.wait(timeout=5)
                            print(f"QR login status: {status}")
                        except Exception as e:
                            print(f"Error checking QR status: {e}")
                    
                    await event.respond(
                        "❌ Login not detected.\n"
                        "Let me try to reset the connection...\n"
                        "Please wait a moment and try /confirm again."
                    )
                    
                    # Try to reset the client
                    try:
                        print("Attempting to reset client connection...")
                        await state.client.disconnect()
                        await state.client.connect()
                    except Exception as e:
                        print(f"Error resetting connection: {e}")
                    
            except Exception as e:
                print(f"Error in confirm_login: {str(e)}")
                await event.respond(
                    "❌ Error checking login status.\n"
                    "Please use /start to try again."
                )
                del user_states[user_id]

        @bot.on(events.NewMessage(pattern='/stop'))
        async def stop_command(event):
            """Stop the sniper process"""
            try:
                user_id = event.sender_id
                chat_id = event.chat_id
                
                if user_id not in user_states:
                    await event.respond("❌ No active sniper found. Use /start to begin.")
                    return
                    
                state = user_states[user_id]
                
                if not state.sniper_running or not state.process:
                    await event.respond("❌ No active sniper found. Use /start to begin.")
                    return
                    
                try:
                    # Kill the sniper process
                    state.process.kill()
                    await state.process.wait()  # Wait for process to end
                    print(f"Stopped sniper process for user {user_id}")
                    
                    # Reset state
                    state.sniper_running = False
                    state.process = None
                    state.sniper_id = None
                    state.waiting_for_channel = False
                    state.waiting_for_access_code = False
                    state.waiting_for_qr_scan = False
                    
                    await event.respond(
                        "✅ Sniper stopped successfully!\n\n"
                        "Use /start to start a new session."
                    )
                    
                except Exception as e:
                    print(f"Error stopping sniper: {str(e)}")
                    await event.respond(
                        f"❌ Error stopping sniper: {str(e)}\n"
                        "Please try again or restart the bot."
                    )
                    
            except Exception as e:
                print(f"Error in stop command: {str(e)}")
                await event.respond("❌ An error occurred. Please try again.")

        @bot.on(events.NewMessage(pattern='/status'))
        async def status_command(event):
            """Check sniper status"""
            try:
                user_id = event.sender_id
                chat_id = event.chat_id
                
                if user_id not in user_states:
                    await event.respond(
                        "📊 **Status Report**\n"
                        "🔴 Status: Not running\n"
                        "ℹ️ Use /start to begin monitoring."
                    )
                    return
                    
                state = user_states[user_id]
                
                if state.sniper_running and state.process:
                    # Check if process is actually running
                    try:
                        state.process.kill()  # This will raise ProcessLookupError if process is not running
                        state.process.kill()  # Undo the kill if it worked
                        is_running = True
                    except ProcessLookupError:
                        is_running = False
                        state.sniper_running = False
                        state.process = None
                    
                    if is_running:
                        status_msg = (
                            "📊 **Status Report**\n"
                            "🟢 Status: Active\n"
                            f"📡 Monitoring: `{state.target_channel}`\n"
                            f"⏱ Uptime: {calculate_uptime(state.start_time)}\n"
                            "ℹ️ Use /stop to stop monitoring."
                        )
                    else:
                        status_msg = (
                            "📊 **Status Report**\n"
                            "🔴 Status: Process died\n"
                            "ℹ️ Use /start to restart monitoring."
                        )
                else:
                    status_msg = (
                        "📊 **Status Report**\n"
                        "🔴 Status: Not running\n"
                        "ℹ️ Use /start to begin monitoring."
                    )
                    
                await event.respond(status_msg, parse_mode='md')
                
            except Exception as e:
                print(f"Error in status command: {str(e)}")
                await event.respond("❌ An error occurred while checking status.")

        @bot.on(events.NewMessage)
        async def message_handler(event):
            """Handle user messages"""
            try:
                if event.message.text.startswith('/'):
                    return  # Skip command messages
                    
                user_id = event.sender_id
                chat_id = event.chat_id
                message = event.raw_text.strip()
                
                if user_id not in user_states:
                    user_states[user_id] = UserState()
                
                state = user_states[user_id]
                
                # Only process messages if we're in a valid state
                if state.sniper_running:
                    return  # Ignore messages if sniper is already running
                    
                if state.waiting_for_access_code:
                    if message == ACCESS_CODE:
                        print(f"Access code verified for user {user_id}")
                        state.waiting_for_access_code = False
                        
                        # Create QR login session
                        state.client = TelegramClient(
                            StringSession(),
                            API_ID,
                            API_HASH,
                            device_model="Windows",
                            system_version="10",
                            app_version="1.0",
                            lang_code="en",
                            system_lang_code="en"
                        )
                        await state.client.connect()
                        
                        # Generate QR login
                        state.qr_login = await state.client.qr_login()
                        state.waiting_for_qr_scan = True
                        
                        try:
                            # Generate QR code image
                            qr_image = await generate_qr(state.qr_login.url)
                            
                            # Send QR code
                            qr_message = await bot.send_message(
                                chat_id,
                                "🔐 Please scan this QR code with your Telegram app to login:\n\n" +
                                "1. Open Telegram on your phone\n" +
                                "2. Go to Settings > Devices > Link Desktop Device\n" +
                                "3. Scan this QR code",
                                file=qr_image
                            )
                            
                            state.qr_message_id = qr_message.id
                            print(f"QR login session created for user {user_id}")
                            print(f"QR code sent to user {user_id}")
                            
                            # Start QR login check
                            asyncio.create_task(check_qr_login(bot, chat_id, user_id, state))
                            
                        except Exception as e:
                            print(f"Error sending QR code: {str(e)}")
                            await bot.send_message(
                                chat_id,
                                "❌ Error generating QR code. Please use /start to try again."
                            )
                            state.waiting_for_qr_scan = False
                            
                    else:
                        await bot.send_message(chat_id, "❌ Invalid access code. Please try again.")
                        
                elif state.waiting_for_channel:
                    if not message.startswith('@'):
                        await bot.send_message(
                            chat_id,
                            "❌ Invalid channel format. Please enter a channel username starting with @"
                        )
                        return
                        
                    print(f"Processing channel input from user {user_id}")
                    
                    try:
                        # Start the sniper process with chat_id
                        state.process, state.sniper_id = await start_sniper(state.session_string, message, chat_id)
                        print(f"Sniper started for user {user_id} on channel {message}")
                        
                        await bot.send_message(
                            chat_id,
                            "✅ Sniper started successfully!\n\n" +
                            "I will now monitor the channel for invite links and automatically join them.\n\n" +
                            "You can stop the sniper at any time by sending /stop"
                        )
                        
                        state.waiting_for_channel = False
                        state.sniper_running = True
                        
                    except Exception as e:
                        print(f"Error starting sniper: {str(e)}")
                        await bot.send_message(
                            chat_id,
                            f"❌ Error starting sniper: {str(e)}\n" +
                            "Please try again with a different channel or use /start to restart."
                        )
                        
            except Exception as e:
                print(f"Error in message_handler: {str(e)}")
                
        print("🤖 Bot is ready! Press Ctrl+C to stop.")
        await bot.run_until_disconnected()
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        
def calculate_uptime(start_time):
    """Calculate uptime from start time"""
    if not start_time:
        return "Unknown"
    
    delta = datetime.now() - start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    
    return " ".join(parts)

if __name__ == '__main__':
    asyncio.run(main())
