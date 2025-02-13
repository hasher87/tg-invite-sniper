import os
import re
import asyncio
import uuid
import json
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.sessions import StringSession
from colorama import Fore, Style
import subprocess
import time
from collections import OrderedDict

# Load environment variables
load_dotenv()

# Bot credentials (only needs bot token)
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')

# Store user states and sessions
user_states = {}
user_processes = {}

class UserState:
    def __init__(self):
        self.phone = None
        self.waiting_for_phone = False
        self.waiting_for_code = False
        self.waiting_for_2fa = False
        self.waiting_for_channel = False
        self.client = None
        self.session_string = None

async def start_sniper_process(phone, session_string, channel):
    """Start a new sniper process for a user"""
    process = subprocess.Popen(
        ['python', 'invite_sniper.py'],
        env={
            'API_ID': str(API_ID),
            'API_HASH': API_HASH,
            'SESSION_STRING': session_string,
            'TARGET_CHANNEL': channel,
            'PATH': os.environ['PATH']
        }
    )
    return process

async def main():
    try:
        print("🚀 Starting bot...")
        
        # Initialize bot client
        bot = TelegramClient(
            StringSession(),
            API_ID,
            API_HASH
        )
        await bot.start(bot_token=BOT_TOKEN)
        
        print("✅ Bot started successfully!")
        
        @bot.on(events.NewMessage(pattern='/start'))
        async def start_command(event):
            user_id = event.sender_id
            
            # Reset user state
            user_states[user_id] = UserState()
            user_states[user_id].waiting_for_phone = True
            
            await event.respond(
                "Welcome to Invite Sniper Bot! 🚀\n\n"
                "To get started, I'll need to create a session for you.\n"
                "Please send your phone number in international format (e.g., +1234567890)"
            )

        @bot.on(events.NewMessage(pattern='/stop'))
        async def stop_command(event):
            user_id = event.sender_id
            if user_id in user_processes:
                process = user_processes[user_id]
                process.terminate()
                del user_processes[user_id]
                await event.respond("✅ Sniper has been stopped.")
            else:
                await event.respond("❌ No active sniper found.")

        @bot.on(events.NewMessage)
        async def message_handler(event):
            if event.raw_text.startswith('/'):
                return
                
            user_id = event.sender_id
            if user_id not in user_states:
                return
                
            state = user_states[user_id]
            
            if state.waiting_for_phone:
                phone = event.raw_text.strip()
                state.phone = phone
                state.waiting_for_phone = False
                state.waiting_for_code = True
                
                # Initialize client for authentication
                client = TelegramClient(
                    StringSession(),
                    API_ID,
                    API_HASH
                )
                await client.connect()
                
                try:
                    await client.send_code_request(phone)
                    state.client = client
                    await event.respond(
                        "📱 Please enter the verification code sent to your phone\n"
                        "(If you have 2FA enabled, you'll be asked for your password next)"
                    )
                except Exception as e:
                    await event.respond(f"❌ Error: {str(e)}\nPlease try again with a valid phone number.")
                    state.waiting_for_phone = True
                    
            elif state.waiting_for_code:
                try:
                    code = event.raw_text.strip()
                    await state.client.sign_in(state.phone, code)
                    
                    # Save session string
                    state.session_string = state.client.session.save()
                    state.waiting_for_code = False
                    state.waiting_for_channel = True
                    
                    await event.respond(
                        "✅ Successfully authenticated!\n\n"
                        "Now, please enter the target channel username (e.g., @channel)"
                    )
                    
                except SessionPasswordNeededError:
                    state.waiting_for_code = False
                    state.waiting_for_2fa = True
                    await event.respond("🔐 Please enter your 2FA password:")
                except PhoneCodeInvalidError:
                    await event.respond("❌ Invalid code. Please try again:")
                except Exception as e:
                    await event.respond(f"❌ Error: {str(e)}\nPlease start over with /start")
                    del user_states[user_id]
                    
            elif state.waiting_for_2fa:
                try:
                    password = event.raw_text.strip()
                    await state.client.sign_in(password=password)
                    
                    # Save session string
                    state.session_string = state.client.session.save()
                    state.waiting_for_2fa = False
                    state.waiting_for_channel = True
                    
                    await event.respond(
                        "✅ Successfully authenticated!\n\n"
                        "Now, please enter the target channel username (e.g., @channel)"
                    )
                    
                except Exception as e:
                    await event.respond(f"❌ Error: {str(e)}\nPlease start over with /start")
                    del user_states[user_id]
                    
            elif state.waiting_for_channel:
                channel = event.raw_text.strip()
                
                if not channel.startswith('@'):
                    await event.respond("❌ Please provide a valid channel username starting with @")
                    return
                
                try:
                    # Stop existing process if any
                    if user_id in user_processes:
                        user_processes[user_id].terminate()
                    
                    # Start new sniper process
                    process = await start_sniper_process(
                        state.phone,
                        state.session_string,
                        channel
                    )
                    user_processes[user_id] = process
                    
                    await event.respond(
                        "✅ Sniper started successfully!\n\n"
                        "The bot is now monitoring the channel for invite links.\n"
                        "Use /stop to stop the sniper when you're done."
                    )
                    
                except Exception as e:
                    await event.respond(f"❌ Error starting sniper: {str(e)}")
                
                del user_states[user_id]
        
        print("🤖 Bot is ready! Press Ctrl+C to stop.")
        await bot.run_until_disconnected()
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        
if __name__ == '__main__':
    # Clean up any existing processes on restart
    asyncio.run(main())
