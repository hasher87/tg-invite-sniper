import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import InviteHashExpiredError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.network import MTProtoSender
from telethon.crypto import AuthKey
from telethon.network.connection import ConnectionTcpAbridged
from colorama import Fore, Style
import time
from collections import OrderedDict

# Load environment variables
load_dotenv()

# Telegram API credentials
API_ID = int(os.getenv('API_ID'))
API_HASH = os.getenv('API_HASH')

# Optimize regex pattern for faster matching
INVITE_PATTERN = re.compile(r't\.me/\+([a-zA-Z0-9_-]+)', re.IGNORECASE | re.ASCII)

# Connection pool for request management
class ConnectionPool:
    def __init__(self, size=5):
        self.size = size
        self.available = asyncio.Queue()
        self.connections = []

    async def init_pool(self, client):
        for _ in range(self.size):
            conn = await client.connect()
            self.connections.append(conn)
            await self.available.put(conn)

    async def get_connection(self):
        return await self.available.get()

    async def release_connection(self, conn):
        await self.available.put(conn)

class InviteCache:
    def __init__(self, max_size=10000):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.pattern = INVITE_PATTERN  # Store pattern reference
    
    def add(self, link: str, status: str):
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
        self.cache[link] = {
            'status': status,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def exists(self, link: str) -> bool:
        return link in self.cache

class OptimizedClient:
    def __init__(self, client):
        self.client = client
        self._request = ImportChatInviteRequest  # Cache the request class
    
    async def initialize(self):
        """Initialize optimized components"""
        pass
    
    async def join_chat(self, invite_hash: str) -> bool:
        """Optimized chat joining using ImportChatInviteRequest"""
        try:
            # Remove any URL components and the '+' prefix
            hash_only = invite_hash.split('+')[-1] if '+' in invite_hash else invite_hash
            
            # Use cached request class
            await asyncio.wait_for(
                self.client(self._request(hash_only)),
                timeout=0.1
            )
            return True
        except asyncio.TimeoutError:
            return False
        except ValueError as ve:
            return False
        except Exception as e:
            return False

async def main():
    """Main entry point for the invite sniper bot."""
    
    phone = input("Enter your phone number (international format): ").strip().replace(' ', '')
    target_chat = input("Enter target channel ID (with or without -100 prefix): ").strip()
    
    # Optimized client configuration with reduced overhead
    client = TelegramClient(
        'sniper_session', 
        API_ID, 
        API_HASH,
        connection=ConnectionTcpAbridged,
        use_ipv6=False,
        connection_retries=1,
        request_retries=1,
        flood_sleep_threshold=0,
        auto_reconnect=True,
        retry_delay=0,
        device_model="SniperX",
        app_version="4.0.0",
        receive_updates=False,  # Disable update handling for better performance
        catch_up=False,  # Disable catch-up on missed updates
    )

    try:
        await client.start(phone, max_attempts=1)
    except Exception as e:
        print(f"{Fore.RED}🚨 Connection failed: {str(e)}{Style.RESET_ALL}")
        return

    try:
        input_entity = await client.get_input_entity(target_chat)
        full_entity = await client.get_entity(input_entity)
        print(f"\nConnected to: {full_entity.title}")
    except Exception as e:
        print(f"Error connecting to channel: {str(e)}")
        await client.disconnect()
        return

    # Initialize optimized components
    optimized_client = OptimizedClient(client)
    await optimized_client.initialize()
    
    # Initialize in-memory cache
    invite_cache = InviteCache()

    # Pre-compile message handler for better performance
    message_handler = None

    @client.on(events.NewMessage(chats=input_entity))
    async def handler(event):
        """Ultra-optimized message handler"""
        try:
            detection_time = time.perf_counter()
            text = event.raw_text  # Use raw_text instead of text for better performance
            
            if matches := INVITE_PATTERN.finditer(text):
                # Process matches sequentially for better success rate
                for match in matches:
                    await process_invite(match, detection_time, invite_cache, optimized_client)
    
        except Exception as e:
            pass  # Skip error handling for better performance

    async def process_invite(match, detection_time, cache, client):
        """Ultra-optimized invite processing"""
        invite_hash = match.group(1)
        
        # Skip link construction unless needed for logging
        if cache.exists(f"t.me/+{invite_hash}"):
            return
            
        detect_latency = (time.perf_counter() - detection_time) * 1000
        
        join_start = time.perf_counter()
        success = await client.join_chat(invite_hash)
        join_time = (time.perf_counter() - join_start) * 1000
        
        link = f"https://t.me/+{invite_hash}"  # Construct link only when needed
        if success:
            print(f"{Fore.GREEN}✅ {detect_latency:.2f}ms/{join_time:.2f}ms | {link}{Style.RESET_ALL}")
            cache.add(link, 'joined')
        else:
            print(f"{Fore.RED}❌ {detect_latency:.2f}ms/{join_time:.2f}ms | {link}{Style.RESET_ALL}")
            cache.add(link, 'failed')

    print(f"{Fore.GREEN}🚀 Ultra-optimized invite sniper is running...{Style.RESET_ALL}")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())