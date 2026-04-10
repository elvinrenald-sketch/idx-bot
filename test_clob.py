import asyncio
import aiohttp

async def main():
    async with aiohttp.ClientSession() as session:
        t1 = "8501497159083948713316135768103773293754490207922884688769443031624417212426"
        async with session.post("https://clob.polymarket.com/spreads", json=[{"token_id": t1}]) as r:
            print(f"POST spreads: {r.status} {await r.text()}")
            
asyncio.run(main())
