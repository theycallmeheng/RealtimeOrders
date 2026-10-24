"""Actual I/O and task cleanup through each supported server loop factory."""
import asyncio
import importlib.util
import sys
import pytest
from app.event_loop import new_event_loop


@pytest.mark.parametrize('mode',['asyncio','winloop'])
def test_loop_tcp_unicode_and_task_cancellation(monkeypatch,mode):
    if mode=='winloop' and (sys.platform!='win32' or importlib.util.find_spec('winloop') is None):
        pytest.skip('Windows accelerator is not installed on this platform')
    monkeypatch.setenv('REALTIMEORDERS_EVENT_LOOP',mode)

    async def scenario():
        finished=asyncio.Event()
        async def echo(reader,writer):
            try:
                data=await reader.readexactly(len(payload))
                writer.write(data)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
                finished.set()
        payload='Đồng bộ đơn hàng 🛒'.encode('utf-8')
        server=await asyncio.start_server(echo,'127.0.0.1',0)
        try:
            reader,writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1])
            try:
                writer.write(payload)
                await writer.drain()
                assert await asyncio.wait_for(reader.readexactly(len(payload)),2)==payload
                await asyncio.wait_for(finished.wait(),2)
            finally:
                writer.close()
                await writer.wait_closed()
            blocked=asyncio.create_task(asyncio.Event().wait())
            await asyncio.sleep(0)
            blocked.cancel()
            with pytest.raises(asyncio.CancelledError):await blocked
        finally:
            server.close()
            await server.wait_closed()

    loop=new_event_loop()
    try:loop.run_until_complete(scenario())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
