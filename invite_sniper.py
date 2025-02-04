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
from telethon.network.connection import ConnectionTcpAbridged
import time

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
    
    client = TelegramClient(
        'sniper_session', 
        API_ID, 
        API_HASH,
        connection=ConnectionTcpAbridged,  # Use the connection class directly
        connection_retries=0,  # Updated parameter name
        auto_reconnect=False,
        request_retries=0,
        flood_sleep_threshold=0,
        workers=20
    )
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

    # Preload existing links to memory
    await c.execute('SELECT link FROM invites')
    existing_links = {row[0] async for row in c}
    
    @client.on(events.NewMessage(chats=input_entity))
    async def handler(event):
        try:
            detection_time = time.perf_counter()  # More precise timing
            text = event.message.text
            
            if matches := INVITE_PATTERN.finditer(text):
                # Process matches concurrently
                await asyncio.gather(*[
                    process_invite(match, detection_time, existing_links)
                    for match in matches
                ])
    
        except Exception as e:
            print(f"{Fore.RED}🚨 Critical error: {str(e)}{Style.RESET_ALL}")

    async def process_invite(match, detection_time, cache):
        invite_hash = match.group(1)
        link = f"https://t.me/+{invite_hash}"
        
        if link in cache:
            return
            
        detect_latency = (time.perf_counter() - detection_time) * 1000
        print(f"{Fore.CYAN}⌛ Detection: {detect_latency:.2f}ms{Style.RESET_ALL}")
        
        join_start = time.perf_counter()
        try:
            # Use bare send instead of full request method
            await client._sender.send(ImportChatInviteRequest(invite_hash))
            join_time = (time.perf_counter() - join_start) * 1000
            print(f"{Fore.GREEN}✅ Joined in {join_time:.2f}ms{Style.RESET_ALL} | {link}")
            cache.add(link)
            
            # Queue write operation instead of immediate commit
            asyncio.create_task(queue_write(link, 'joined'))
            
        except InviteHashExpiredError:
            status = 'expired'
            print(f"{Fore.RED}❌ Expired link: {link}{Style.RESET_ALL}")
            asyncio.create_task(queue_write(link, status))
        except ValueError as ve:
            if "A wait of" in str(ve):
                status = 'already member'
                print(f"{Fore.YELLOW}ℹ️ Already in group: {link}{Style.RESET_ALL}")
                asyncio.create_task(queue_write(link, status))
            else:
                status = f'error: {str(ve)}'
                print(f"{Fore.RED}⚠️ Error joining {link}: {str(ve)}{Style.RESET_ALL}")
                asyncio.create_task(queue_write(link, status))
        except Exception as e:
            join_time = (time.perf_counter() - join_start) * 1000
            print(f"{Fore.RED}⚠️ Failed in {join_time:.2f}ms{Style.RESET_ALL} | {str(e)}")
            asyncio.create_task(queue_write(link, status))

    # Batch write queue system
    write_queue = []
    async def queue_write(link, status):
        write_queue.append((
            link,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            status
        ))
        
        if len(write_queue) >= 5:  # Batch every 5 entries
            await bulk_write()
    
    async def bulk_write():
        nonlocal write_queue
        try:
            await c.executemany(
                '''INSERT OR IGNORE INTO invites VALUES (?, ?, ?)''',
                write_queue
            )
            await conn.commit()
        finally:
            write_queue = []

    print("Invite sniper is actively monitoring...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main()) 