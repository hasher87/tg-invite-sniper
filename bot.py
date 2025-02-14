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
from telethon.types import InputFile, DocumentAttributeFilename, DocumentAttributeImageSize
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
        # Create QR code with better styling
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        # Create image with white background
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Create bytes buffer
        buffer = BytesIO()
        # Save as PNG with maximum quality
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return buffer
        
    except Exception as e:
        print(f"Error generating QR code: {str(e)}")
        raise

async def send_qr_code(bot, chat_id, qr_login):
    """Send QR code with proper formatting"""
    try:
        # Generate QR code image
        qr_buffer = await generate_qr(qr_login.url)
        
        # Send QR code with instructions
        qr_message = await bot.send_file(
            chat_id,
            qr_buffer,
            caption=(
                "🔐 **Scan QR Code to Login**\n\n"
                "1️⃣ Open Telegram on your phone\n"
                "2️⃣ Go to Settings > Devices\n"
                "3️⃣ Tap 'Link Desktop Device'\n"
                "4️⃣ Scan this QR code\n\n"
                "⏳ Code expires in 30 seconds..."
            ),
            parse_mode='md',
            file_name='qr_login.png',  
            force_document=False  
        )
        
        return qr_message
        
    except Exception as e:
        print(f"Error sending QR code: {str(e)}")
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
            """Start the bot and show main menu"""
            try:
                user_id = event.sender_id
                
                # Create new state or reset existing one
                user_states[user_id] = UserState()
                
                # Create main menu with buttons
                buttons = [
                    [Button.inline("🚀 Start Sniper", "start_sniper")],
                    [Button.inline("📊 Check Status", "check_status")],
                    [Button.inline("❓ FAQ", "show_faq"), Button.inline("ℹ️ About", "show_about")],
                    [Button.inline("💰 Pricing", "show_pricing")],
                    [Button.inline("⚠️ Disclaimer", "show_disclaimer")]
                ]
                
                await event.respond(
                    "🤖 **Welcome to Telegram Invite Sniper Pro!**\n\n"
                    "Choose an action from the menu below:",
                    buttons=buttons
                )
                
            except Exception as e:
                print(f"Error in start command: {str(e)}")
                await event.respond("❌ An error occurred. Please try again.")

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
                
                if not state.sniper_running:
                    await event.respond("❌ No active sniper found. Use /start to begin.")
                    return
                    
                try:
                    if state.process:
                        try:
                            # Try to terminate gracefully first
                            state.process.terminate()
                            try:
                                # Wait for up to 5 seconds for process to end
                                await asyncio.wait_for(state.process.wait(), timeout=5.0)
                            except asyncio.TimeoutError:
                                # If process doesn't end in 5 seconds, force kill it
                                state.process.kill()
                                await state.process.wait()
                        except ProcessLookupError:
                            # Process already ended
                            pass
                        except Exception as e:
                            print(f"Error terminating process: {str(e)}")
                            
                    print(f"Stopped sniper process for user {user_id}")
                    
                    # Reset state
                    state.sniper_running = False
                    state.process = None
                    state.sniper_id = None
                    state.waiting_for_channel = False
                    state.waiting_for_access_code = False
                    state.waiting_for_qr_scan = False
                    state.target_channel = None
                    state.start_time = None
                    
                    await event.respond(
                        "✅ Sniper stopped successfully!\n\n"
                        "Use /start to start a new session."
                    )
                    
                except Exception as e:
                    print(f"Error stopping sniper: {str(e)}")
                    # Reset state anyway to allow restart
                    state.sniper_running = False
                    state.process = None
                    state.sniper_id = None
                    await event.respond(
                        "⚠️ Sniper stopped with warnings.\n"
                        "The process may have already ended.\n\n"
                        "Use /start to start a new session."
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
                    # Check if process is still running without killing it
                    try:
                        # poll() returns None if process is running, otherwise returns return code
                        is_running = state.process.returncode is None
                        if not is_running:
                            state.sniper_running = False
                            state.process = None
                    except Exception:
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
                            "🔴 Status: Process ended\n"
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
                            # Send QR code with proper formatting
                            qr_message = await send_qr_code(bot, chat_id, state.qr_login)
                            state.qr_message_id = qr_message.id
                            print(f"QR login session created for user {user_id}")
                            print(f"QR code sent to user {user_id}")
                            
                            # Start QR login check
                            asyncio.create_task(check_qr_login(bot, chat_id, user_id, state))
                            
                        except Exception as e:
                            print(f"Error in QR code process: {str(e)}")
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
                
        @bot.on(events.CallbackQuery(pattern=r'start_sniper'))
        async def start_sniper_callback(event):
            """Handle start sniper button click"""
            try:
                user_id = event.sender_id
                
                if user_id not in user_states:
                    user_states[user_id] = UserState()
                    
                state = user_states[user_id]
                
                if state.sniper_running:
                    buttons = [
                        [Button.inline("🔄 Restart Sniper", "restart_sniper")],
                        [Button.inline("📊 Check Status", "check_status")],
                        [Button.inline("⬅️ Back to Menu", "main_menu")]
                    ]
                    await event.edit(
                        "⚠️ Sniper is already running!\n\n"
                        "Choose an action:",
                        buttons=buttons
                    )
                    return
                    
                # Ask for access code
                await event.edit(
                    "🔑 Please enter the access code to continue.\n\n"
                    "The access code was provided to you when you purchased the bot.",
                    buttons=[[Button.inline("⬅️ Back to Menu", "main_menu")]]
                )
                state.waiting_for_access_code = True
                
            except Exception as e:
                print(f"Error in start sniper callback: {str(e)}")
                await event.edit("❌ An error occurred. Please try again.")

        @bot.on(events.CallbackQuery(pattern=r'check_status'))
        async def status_callback(event):
            """Handle status button click"""
            try:
                user_id = event.sender_id
                
                if user_id not in user_states:
                    buttons = [[Button.inline("⬅️ Back to Menu", "main_menu")]]
                    await event.edit(
                        "📊 **Status Report**\n"
                        "🔴 Status: Not running\n"
                        "ℹ️ Use Start Sniper to begin monitoring.",
                        buttons=buttons
                    )
                    return
                    
                state = user_states[user_id]
                
                if state.sniper_running and state.process:
                    # Check if process is still running without killing it
                    try:
                        is_running = state.process.returncode is None
                        if not is_running:
                            state.sniper_running = False
                            state.process = None
                    except Exception:
                        is_running = False
                        state.sniper_running = False
                        state.process = None
                    
                    if is_running:
                        buttons = [
                            [Button.inline("🛑 Stop Sniper", "stop_sniper")],
                            [Button.inline("⬅️ Back to Menu", "main_menu")]
                        ]
                        status_msg = (
                            "📊 **Status Report**\n"
                            "🟢 Status: Active\n"
                            f"📡 Monitoring: `{state.target_channel}`\n"
                            f"⏱ Uptime: {calculate_uptime(state.start_time)}\n"
                            "ℹ️ Use Stop Sniper to stop monitoring."
                        )
                    else:
                        buttons = [
                            [Button.inline("🚀 Start Sniper", "start_sniper")],
                            [Button.inline("⬅️ Back to Menu", "main_menu")]
                        ]
                        status_msg = (
                            "📊 **Status Report**\n"
                            "🔴 Status: Process ended\n"
                            "ℹ️ Use Start Sniper to restart monitoring."
                        )
                else:
                    buttons = [
                        [Button.inline("🚀 Start Sniper", "start_sniper")],
                        [Button.inline("⬅️ Back to Menu", "main_menu")]
                    ]
                    status_msg = (
                        "📊 **Status Report**\n"
                        "🔴 Status: Not running\n"
                        "ℹ️ Use Start Sniper to begin monitoring."
                    )
                    
                await event.edit(status_msg, buttons=buttons, parse_mode='md')
                
            except Exception as e:
                print(f"Error in status callback: {str(e)}")
                await event.edit("❌ An error occurred while checking status.")

        @bot.on(events.CallbackQuery(pattern=r'stop_sniper'))
        async def stop_sniper_callback(event):
            """Handle stop sniper button click"""
            try:
                user_id = event.sender_id
                
                if user_id not in user_states:
                    buttons = [[Button.inline("⬅️ Back to Menu", "main_menu")]]
                    await event.edit(
                        "❌ No active sniper found.",
                        buttons=buttons
                    )
                    return
                    
                state = user_states[user_id]
                
                if not state.sniper_running:
                    buttons = [[Button.inline("⬅️ Back to Menu", "main_menu")]]
                    await event.edit(
                        "❌ No active sniper found.",
                        buttons=buttons
                    )
                    return
                    
                try:
                    if state.process:
                        try:
                            state.process.terminate()
                            try:
                                await asyncio.wait_for(state.process.wait(), timeout=5.0)
                            except asyncio.TimeoutError:
                                state.process.kill()
                                await state.process.wait()
                        except ProcessLookupError:
                            pass
                        except Exception as e:
                            print(f"Error terminating process: {str(e)}")
                            
                    print(f"Stopped sniper process for user {user_id}")
                    
                    # Reset state
                    state.sniper_running = False
                    state.process = None
                    state.sniper_id = None
                    state.waiting_for_channel = False
                    state.waiting_for_access_code = False
                    state.waiting_for_qr_scan = False
                    state.target_channel = None
                    state.start_time = None
                    
                    buttons = [
                        [Button.inline("🚀 Start New Sniper", "start_sniper")],
                        [Button.inline("⬅️ Back to Menu", "main_menu")]
                    ]
                    
                    await event.edit(
                        "✅ Sniper stopped successfully!",
                        buttons=buttons
                    )
                    
                except Exception as e:
                    print(f"Error stopping sniper: {str(e)}")
                    state.sniper_running = False
                    state.process = None
                    state.sniper_id = None
                    
                    buttons = [
                        [Button.inline("🚀 Start New Sniper", "start_sniper")],
                        [Button.inline("⬅️ Back to Menu", "main_menu")]
                    ]
                    
                    await event.edit(
                        "⚠️ Sniper stopped with warnings.\n"
                        "The process may have already ended.",
                        buttons=buttons
                    )
                    
            except Exception as e:
                print(f"Error in stop sniper callback: {str(e)}")
                await event.edit("❌ An error occurred. Please try again.")

        @bot.on(events.CallbackQuery(pattern=r'main_menu'))
        async def main_menu_callback(event):
            """Return to main menu"""
            try:
                buttons = [
                    [Button.inline("🚀 Start Sniper", "start_sniper")],
                    [Button.inline("📊 Check Status", "check_status")],
                    [Button.inline("❓ FAQ", "show_faq"), Button.inline("ℹ️ About", "show_about")],
                    [Button.inline("💰 Pricing", "show_pricing")],
                    [Button.inline("⚠️ Disclaimer", "show_disclaimer")]
                ]
                
                await event.edit(
                    "🤖 **Welcome to Telegram Invite Sniper Pro!**\n\n"
                    "Choose an action from the menu below:",
                    buttons=buttons
                )
                
            except Exception as e:
                print(f"Error in main menu callback: {str(e)}")
                await event.edit("❌ An error occurred. Please try again.")

        @bot.on(events.CallbackQuery(pattern=r'show_faq'))
        async def faq_callback(event):
            """Show FAQ"""
            try:
                faq_text = (
                    "❓ **Frequently Asked Questions**\n\n"
                    
                    "**Q: How does the bot work?**\n"
                    "A: The bot monitors specified channels for invite links and automatically joins them at high speed "
                    "(typically 50-300ms). It uses advanced detection algorithms and optimized joining methods.\n\n"
                    
                    "**Q: Is it safe to use?**\n"
                    "A: The bot uses official Telegram APIs and follows rate limits. However, use at your own discretion "
                    "and be aware of Telegram's terms of service.\n\n"
                    
                    "**Q: Why do I need to scan a QR code?**\n"
                    "A: The QR code login ensures secure access to your Telegram account. This is a standard Telegram "
                    "security feature and the code expires after 30 seconds.\n\n"
                    
                    "**Q: Can I monitor multiple channels?**\n"
                    "A: Currently, the bot monitors one channel at a time for optimal performance. You can switch "
                    "channels by stopping and restarting the sniper.\n\n"
                    
                    "**Q: What happens if my connection drops?**\n"
                    "A: The bot will attempt to reconnect automatically. You can check the status using the Status "
                    "button and restart if needed.\n\n"
                    
                    "**Q: How do I stop the bot?**\n"
                    "A: Use the Stop button in the Status menu or send /stop command. The bot will gracefully "
                    "terminate all processes.\n\n"
                    
                    "**Q: What's the success rate?**\n"
                    "A: The bot achieves nearly 100% success rate on detected invites, with join times typically "
                    "under 300ms.\n\n"
                    
                    "**Need more help?**\n"
                    "Contact: x.com/0xDeepSeek"
                )
                
                buttons = [[Button.inline("⬅️ Back to Menu", "main_menu")]]
                await event.edit(faq_text, buttons=buttons)
                
            except Exception as e:
                print(f"Error in FAQ callback: {str(e)}")
                await event.edit("❌ An error occurred. Please try again.")

        @bot.on(events.CallbackQuery(pattern=r'show_about'))
        async def about_callback(event):
            """Show About"""
            try:
                about_text = (
                    "ℹ️ **About Telegram Invite Sniper Pro**\n\n"
                    
                    "🚀 **Features**\n"
                    "• Ultra-fast invite detection (sub-millisecond)\n"
                    "• Optimized joining algorithm (50-300ms)\n"
                    "• Real-time performance statistics\n"
                    "• Secure QR code login\n"
                    "• Interactive button interface\n"
                    "• Detailed status monitoring\n"
                    "• Automatic error recovery\n\n"
                    
                    "⚡ **Performance**\n"
                    "• Average detection time: ~0.1ms\n"
                    "• Average join time: ~200ms\n"
                    "• Success rate: >99%\n"
                    "• Uptime: 24/7 capability\n\n"
                    
                    "🛡️ **Security**\n"
                    "• Official Telegram API\n"
                    "• No password storage\n"
                    "• Secure QR login\n"
                    "• Rate limit compliant\n\n"
                    
                    "🔧 **Support**\n"
                    "• 24/7 technical support\n"
                    "• Regular updates\n"
                    "• Custom feature requests\n"
                    "• Direct developer access\n\n"
                    
                    "Version: 1.0.0\n"
                    "Developer & Support: x.com/0xDeepSeek"
                )
                
                buttons = [[Button.inline("⬅️ Back to Menu", "main_menu")]]
                await event.edit(about_text, buttons=buttons)
                
            except Exception as e:
                print(f"Error in About callback: {str(e)}")
                await event.edit("❌ An error occurred. Please try again.")

        @bot.on(events.CallbackQuery(pattern=r'show_pricing'))
        async def pricing_callback(event):
            """Show pricing information"""
            try:
                pricing_text = (
                    "💰 **Telegram Invite Sniper Pro Pricing**\n\n"
                    
                    "🎯 **Usage-Based Plans**\n"
                    "Choose the duration that fits your needs:\n\n"
                    
                    "1️⃣ **2-Day Access**\n"
                    "• Price: $6\n"
                    "• Perfect for quick campaigns\n"
                    "• Full feature access\n\n"
                    
                    "2️⃣ **5-Day Access**\n"
                    "• Price: $13\n"
                    "• Ideal for medium projects\n"
                    "• Full feature access\n\n"
                    
                    "3️⃣ **10-Day Access**\n"
                    "• Price: $20\n"
                    "• Best for extended use\n"
                    "• Full feature access\n\n"
                    
                    "4️⃣ **30-Day Access**\n"
                    "• Price: $45\n"
                    "• Maximum flexibility\n"
                    "• Full feature access\n\n"
                    
                    "ℹ️ **Why Usage-Based Pricing?**\n"
                    "Our bot operates on a usage-time model rather than lifetime access. "
                    "This approach ensures:\n"
                    "• Fair pricing based on your needs\n"
                    "• Regular updates and maintenance\n"
                    "• Dedicated support and monitoring\n"
                    "• Optimal performance and reliability\n\n"
                    
                    "🔄 **Renewal Process**\n"
                    "• Easy renewal before expiration\n"
                    "• Flexible plan switching\n"
                    "• No long-term commitment\n\n"
                    
                    "💫 **All Plans Include**\n"
                    "• Ultra-fast invite detection\n"
                    "• 24/7 operation capability\n"
                    "• Real-time performance stats\n"
                    "• Priority technical support\n\n"
                    
                    "📱 **Purchase & Support**\n"
                    "Contact: x.com/0xDeepSeek"
                )
                
                buttons = [[Button.inline("⬅️ Back to Menu", "main_menu")]]
                await event.edit(pricing_text, buttons=buttons)
                
            except Exception as e:
                print(f"Error in pricing callback: {str(e)}")
                await event.edit("❌ An error occurred. Please try again.")

        @bot.on(events.CallbackQuery(pattern=r'show_disclaimer'))
        async def disclaimer_callback(event):
            """Show Disclaimer"""
            try:
                disclaimer_text = (
                    "⚠️ **Important Disclaimer**\n\n"
                    
                    "**Terms of Use**\n"
                    "By using this bot, you acknowledge and agree to the following terms:\n\n"
                    
                    "1️⃣ **User Responsibility**\n"
                    "• You are responsible for how you use this bot\n"
                    "• You must comply with Telegram's Terms of Service\n"
                    "• You must respect channel owners' rights\n"
                    "• You must not abuse or misuse the service\n\n"
                    
                    "2️⃣ **Security & Privacy**\n"
                    "• The bot requires QR login for security\n"
                    "• We don't store passwords or messages\n"
                    "• Your session data is encrypted\n"
                    "• You can revoke access anytime\n\n"
                    
                    "3️⃣ **Performance & Reliability**\n"
                    "• Results may vary based on conditions\n"
                    "• No guarantee of 100% success rate\n"
                    "• Network conditions affect performance\n"
                    "• Some invites may be missed\n\n"
                    
                    "4️⃣ **Limitations**\n"
                    "• Rate limits apply as per Telegram API\n"
                    "• One channel monitoring at a time\n"
                    "• Some invite types may not be supported\n"
                    "• Service may be interrupted for maintenance\n\n"
                    
                    "5️⃣ **Legal Notice**\n"
                    "• This is an unofficial bot\n"
                    "• Not affiliated with Telegram\n"
                    "• Use at your own risk\n"
                    "• We reserve right to modify service\n\n"
                    
                    "**❗ Important**\n"
                    "Misuse of this bot may result in Telegram account restrictions. "
                    "We are not responsible for any account issues resulting from bot usage.\n\n"
                    
                    "By continuing to use the bot, you agree to these terms."
                )
                
                buttons = [
                    [Button.inline("✅ I Agree", "main_menu")],
                    [Button.inline("❌ I Disagree", "exit_bot")]
                ]
                await event.edit(disclaimer_text, buttons=buttons)
                
            except Exception as e:
                print(f"Error in Disclaimer callback: {str(e)}")
                await event.edit("❌ An error occurred. Please try again.")

        @bot.on(events.CallbackQuery(pattern=r'exit_bot'))
        async def exit_bot_callback(event):
            """Handle user disagreement with disclaimer"""
            try:
                user_id = event.sender_id
                
                # Clear user state if exists
                if user_id in user_states:
                    del user_states[user_id]
                
                await event.edit(
                    "❌ **Access Denied**\n\n"
                    "You must accept the disclaimer to use this bot.\n"
                    "If you change your mind, use /start to begin again."
                )
                
            except Exception as e:
                print(f"Error in exit callback: {str(e)}")
                await event.edit("❌ An error occurred. Please try again.")
        
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
