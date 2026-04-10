import asyncio, aiohttp

async def api_get(session, url, params=None):
    async with session.get(url, params=params) as r:
        if r.status == 200:
            return await r.json()
        print(f"Error GET: {r.status} {await r.text()}")
        return None

async def main():
    async with aiohttp.ClientSession() as session:
        j = await api_get(session, "https://gamma-api.polymarket.com/markets", {'limit': 5, 'active': 'true'})
        if not j: return
        import json
        tid = ""
        for m in j:
            raw = m.get('clobTokenIds', [])
            if isinstance(raw, str):
                tids = json.loads(raw)
            else:
                tids = raw
            if tids:
                tid = tids[0]
                break
        
        print(f"Valid Token ID: {tid}")
        print("Testing GET /midpoint")
        res = await api_get(session, "https://clob.polymarket.com/midpoint", [('token_id', tid)])
        print(res)
        
        print("Testing GET /midpoints with tokens")
        res2 = await api_get(session, "https://clob.polymarket.com/midpoints", [('token_id', tid)])
        print(res2)

if __name__ == "__main__":
    asyncio.run(main())
