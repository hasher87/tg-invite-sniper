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
        self.client = None
        self.session_string = None
        self.qr_message_id = None
        self.qr_login = None
        self.active_channel = None
        self.process = None
        self.sniper_id = None
        self.sniper_running = False

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

async def start_sniper(session_string, target_channel):
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
            'SESSION_STRING': session_string,  # Pass session string directly
            'TARGET_CHANNEL': str(target_channel),
            'SNIPER_ID': str(sniper_id)
        })
        
        print("Starting sniper with configuration:")
        print(f"Target Channel: {env['TARGET_CHANNEL']}")
        print(f"Session String Length: {len(env['SESSION_STRING'])}")
        
        # Start the sniper process with the clean environment
        process = await asyncio.create_subprocess_exec(
            sys.executable,  # Use current Python interpreter
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
            line_text = line.decode().strip()
            print(f"[{name}] {line_text}")
            
            # Send notifications for important events
            if name == "STDOUT":
                if "Found invite:" in line_text:
                    invite_hash = line_text.split("Found invite:", 1)[1].strip()
                    for user_id, state in user_states.items():
                        if state.sniper_running:
                            await bot.send_message(
                                user_id,
                                f"🔍 Found invite link!\n" +
                                f"⚡️ Processing: {invite_hash}"
                            )
                
                elif "Successfully joined" in line_text:
                    # Extract info from subsequent lines
                    title = line_text.split("Successfully joined", 1)[1].strip().strip('!')
                    for user_id, state in user_states.items():
                        if state.sniper_running:
                            # Wait for the next two lines which contain timing info
                            join_time_line = (await pipe.readline()).decode().strip()
                            detection_line = (await pipe.readline()).decode().strip()
                            stats_line = (await pipe.readline()).decode().strip()
                            
                            # Extract timing information
                            join_time = join_time_line.split("Joined in", 1)[1].strip()
                            detection_time = detection_line.split("Detection:", 1)[1].strip()
                            stats = stats_line.split("Stats:", 1)[1].strip()
                            
                            await bot.send_message(
                                user_id,
                                f"✅ Successfully joined {title}!\n\n" +
                                f"⚡️ Join Time: {join_time}\n" +
                                f"🎯 Detection: {detection_time}\n" +
                                f"📊 {stats}"
                            )
                
                elif "Failed to join" in line_text:
                    # Extract timing info
                    join_time = line_text.split("Failed to join after", 1)[1].strip()
                    for user_id, state in user_states.items():
                        if state.sniper_running:
                            # Get detection time from next line
                            detection_line = (await pipe.readline()).decode().strip()
                            detection_time = detection_line.split("Detection:", 1)[1].strip()
                            
                            await bot.send_message(
                                user_id,
                                f"❌ Failed to join!\n\n" +
                                f"⏱ Attempt took: {join_time}\n" +
                                f"🎯 Detection: {detection_time}"
                            )
                
        except Exception as e:
            print(f"Error reading {name}: {str(e)}")

async def check_qr_login(bot, chat_id, user_id, state):
    """Check QR login status and handle session creation"""
    try:
        qr_login = state.qr_login
        print(f"Starting QR login check for user {user_id}")
        
        # Wait for QR login (60 seconds timeout)
        for _ in range(60):
            if not state.waiting_for_qr_scan:
                print("Login completed, stopping QR check")
                return
            
            try:
                # Check login status
                print("Checking QR login status...")
                status = await qr_login.wait(timeout=5)
                print(f"QR login status: {status}")
                
                # Check if client is authorized
                if await state.client.is_user_authorized():
                    print("User is authorized!")
                    state.session_string = state.client.session.save()
                    state.waiting_for_qr_scan = False
                    state.waiting_for_channel = True
                    
                    await bot.send_message(
                        chat_id,
                        "✅ Successfully logged in!\n\n"
                        "🎯 Now, please enter the target channel username (e.g., @channel)\n\n"
                        "ℹ️ Make sure you've already joined the channel you want to monitor."
                    )
                    print(f"Channel prompt sent to user {user_id}")
                    return  # Exit immediately after successful login
                
            except asyncio.TimeoutError:
                print("Timeout while waiting for QR login, continuing...")
                pass
            except Exception as e:
                print(f"Error checking QR login status: {str(e)}")
                
            await asyncio.sleep(2)
            
        # If we get here, QR code check timeout
        if state.waiting_for_qr_scan:
            print("QR code check timeout")
            await bot.edit_message(
                chat_id,
                state.qr_message_id,
                "ℹ️ QR code check timeout.\n\n"
                "If you've already scanned and approved the login, send /confirm\n"
                "Otherwise, use /start to get a new QR code."
            )
            
    except Exception as e:
        print(f"Error in check_qr_login: {str(e)}")
        await bot.send_message(
            chat_id,
            f"❌ Error during QR login: {str(e)}\n"
            "Please use /start to try again."
        )

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
                    state.waiting_for_channel = True
                    
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

        @bot.on(events.NewMessage)
        async def message_handler(event):
            if event.message.text.startswith('/'):
                return  # Skip command messages
                
            user_id = event.sender_id
            chat_id = event.chat_id
            message = event.raw_text.strip()
            
            if user_id not in user_states:
                user_states[user_id] = UserState()
            
            state = user_states[user_id]
            
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
                    # Start the sniper process
                    state.process, state.sniper_id = await start_sniper(state.session_string, message)
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
                    
        print("🤖 Bot is ready! Press Ctrl+C to stop.")
        await bot.run_until_disconnected()
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        
if __name__ == '__main__':
    asyncio.run(main())
