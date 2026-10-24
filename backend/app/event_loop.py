"""Single-worker loop factory; the Windows accelerator changes no app contract."""
import asyncio
import logging
import os
import sys


def new_event_loop():
    mode=os.environ.get('REALTIMEORDERS_EVENT_LOOP','auto').lower()
    if mode not in ('auto','asyncio','winloop'):
        raise ValueError('REALTIMEORDERS_EVENT_LOOP must be auto, asyncio or winloop')
    if mode=='winloop' or (mode=='auto' and sys.platform=='win32'):
        try:
            import winloop
        except ImportError:
            if mode=='winloop':raise
            logging.getLogger('uvicorn.error').warning(
                'Winloop is unavailable; using standard asyncio. Install backend requirements for the tested Windows configuration.')
        else:
            return winloop.new_event_loop()
    return asyncio.new_event_loop()
