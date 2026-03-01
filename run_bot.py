#!/usr/bin/env python3
"""
Auto-restart bot when code changes
"""

import subprocess
import sys
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class BotReloader(FileSystemEventHandler):
    def __init__(self):
        self.process = None
        self.start_bot()
    
    def start_bot(self):
        if self.process:
            print("Stopping bot...")
            self.process.terminate()
            self.process.wait()
        
        print("Starting bot...")
        self.process = subprocess.Popen([sys.executable, "discord_bot.py"])
    
    def on_modified(self, event):
        if event.src_path.endswith('.py'):
            print(f"\n{event.src_path} changed, restarting...")
            self.start_bot()

if __name__ == "__main__":
    print("Bot auto-reloader started. Press Ctrl+C to stop.")
    
    event_handler = BotReloader()
    observer = Observer()
    observer.schedule(event_handler, path='.', recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        observer.stop()
        if event_handler.process:
            event_handler.process.terminate()
    
    observer.join()
