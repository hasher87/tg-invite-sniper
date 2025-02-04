import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
import aiosqlite
from telethon.errors import InviteHashExpiredError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from colorama import Fore, Style

# Load environment variables
load_dotenv()

# Telegram API credentials
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')

# Invite link pattern
INVITE_PATTERN = re.compile(
    r'(?:https?://)?t\.me/\+([\w-]+)',  # Include hyphen in matching
    re.IGNORECASE
)

async def main():
    # Get user input
    phone = input("Enter your phone number (international format): ")
    target_chat = input("Enter target channel ID (with or without -100 prefix): ")
    
    # Remove the ID conversion logic and use string directly
    target_chat = target_chat.strip()  # Keep as string
    
    client = TelegramClient('sniper_session', API_ID, API_HASH)
    await client.start(phone)
    
    try:
        # Get full entity details
        input_entity = await client.get_input_entity(target_chat)
        full_entity = await client.get_entity(input_entity)
        
        print(f"\nSuccessfully connected to channel:")
        print(f"Title: {full_entity.title}")
        print(f"ID: {full_entity.id}")
        print(f"Username: @{full_entity.username}" if full_entity.username else "Private channel")
        
    except Exception as e:
        print(f"Error connecting to channel: {str(e)}")
        print("Make sure:")
        print("1. You're using the correct channel ID/username")
        print("2. You have joined the channel")
        print("3. The channel exists and is accessible")
        await client.disconnect()
        return
    
    # Replace SQLite connection with async version
    conn = await aiosqlite.connect('invite_links.db')
    c = await conn.cursor()
    await c.execute('''CREATE TABLE IF NOT EXISTS invites
             (link TEXT PRIMARY KEY,
              date TEXT,
              status TEXT)''')
    await conn.commit()

    @client.on(events.NewMessage(chats=input_entity))
    async def handler(event):
        try:
            detection_time = datetime.now().timestamp() * 1000  # Milliseconds
            text = event.message.text
            if matches := INVITE_PATTERN.finditer(text):
                for match in matches:
                    invite_hash = match.group(1)
                    link = f"https://t.me/+{invite_hash}"
                    
                    # Async database check
                    await c.execute('SELECT * FROM invites WHERE link = ?', (link,))
                    if not await c.fetchone():
                        detect_latency = datetime.now().timestamp() * 1000 - detection_time
                        print(f"{Fore.CYAN}⌛ Detection: {detect_latency:.2f}ms{Style.RESET_ALL}")
                        
                        join_start = datetime.now().timestamp() * 1000
                        try:
                            await client(ImportChatInviteRequest(hash=invite_hash))
                            join_time = datetime.now().timestamp() * 1000 - join_start
                            status = 'joined'
                            print(f"{Fore.GREEN}✅ Joined in {join_time:.2f}ms{Style.RESET_ALL} | Total: {detect_latency + join_time:.2f}ms | {link}")
                        except InviteHashExpiredError:
                            status = 'expired'
                            print(f"{Fore.RED}❌ Expired link: {link}{Style.RESET_ALL}")
                        except ValueError as ve:
                            if "A wait of" in str(ve):
                                status = 'already member'
                                print(f"{Fore.YELLOW}ℹ️ Already in group: {link}{Style.RESET_ALL}")
                            else:
                                status = f'error: {str(ve)}'
                                print(f"{Fore.RED}⚠️ Error joining {link}: {str(ve)}{Style.RESET_ALL}")
                        except Exception as e:
                            join_time = datetime.now().timestamp() * 1000 - join_start
                            print(f"{Fore.RED}⚠️ Failed in {join_time:.2f}ms{Style.RESET_ALL} | {str(e)}")
                        
                        # Batch insert operations
                        await c.execute('''INSERT OR IGNORE INTO invites 
                                       VALUES (?, ?, ?)''',
                                    (link, 
                                     datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                     status))
                        await conn.commit()
        
        except Exception as e:
            print(f"{Fore.RED}🚨 Critical error: {str(e)}{Style.RESET_ALL}")

    print("Invite sniper is actively monitoring...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main()) 