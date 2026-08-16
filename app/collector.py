import asyncio, json, logging, time, uuid
import websockets
from .config import *
from .db import db
from .wfm import stats, normalize, WFMClient

log=logging.getLogger('wfm.collector')

class Collector:
    def __init__(self, client):
        self.client=client
        self.stop=asyncio.Event()
        self.dirty=asyncio.Queue()
        self.queued=set()

    def mark(self,item_id):
        if item_id and item_id not in self.queued:
            self.queued.add(item_id); self.dirty.put_nowait(item_id)

    async def catalog(self):
        items=await self.client.items(); now=time.time()
        with db() as c:
            for it in items:
                iid=str(it.get('id') or ''); slug=it.get('slug')
                if not iid or not slug: continue
                c.execute('''INSERT INTO items(id,slug,name,category,dirty,next_refresh,updated_at)
                VALUES(?,?,?,?,1,0,?) ON CONFLICT(id) DO UPDATE SET slug=excluded.slug,name=excluded.name,category=excluded.category''',
                          (iid,slug,item_name_safe(it),it.get('category'),now))
        log.info('catalog: %d items',len(items))

    async def recent_mark(self):
        for o in await self.client.recent(): self.mark(str(o.get('itemId')) if o.get('itemId') else None)

    async def refresh(self,iid):
        with db() as c:
            r=c.execute('SELECT slug FROM items WHERE id=?',(iid,)).fetchone()
        if not r: return
        try: raw=await self.client.item_orders(r['slug'])
        except Exception: log.exception('refresh failed %s',r['slug']); return
        s=stats([normalize(o) for o in raw]); now=time.time()
        with db() as c:
            c.execute('''INSERT INTO market(item_id,min_price,median,avg_price,p25,p75,buy_max,sellers,buyers,seller_qty,buyer_qty,liquidity,score,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET min_price=excluded.min_price,median=excluded.median,avg_price=excluded.avg_price,p25=excluded.p25,p75=excluded.p75,buy_max=excluded.buy_max,sellers=excluded.sellers,buyers=excluded.buyers,seller_qty=excluded.seller_qty,buyer_qty=excluded.buyer_qty,liquidity=excluded.liquidity,score=excluded.score,updated_at=excluded.updated_at''',
            (iid,s['min_price'],s['median'],s['avg_price'],s['p25'],s['p75'],s['buy_max'],s['sellers'],s['buyers'],s['seller_qty'],s['buyer_qty'],s['liquidity'],s['score'],now))
            if s['median'] is not None:
                c.execute('INSERT INTO price_history VALUES(?,?,?,?,?,?,?)',(iid,now,s['min_price'],s['median'],s['buy_max'],s['liquidity'],s['score']))
            c.execute('UPDATE items SET dirty=0,next_refresh=?,updated_at=? WHERE id=?',(now+REFRESH_INTERVAL_SECONDS,now,iid))
        self.queued.discard(iid)

    async def batch(self):
        with db() as c:
            rows=c.execute('SELECT id FROM items WHERE dirty=1 OR next_refresh<=? ORDER BY dirty DESC,next_refresh LIMIT ?', (time.time(),REFRESH_BATCH)).fetchall()
        for r in rows:self.mark(r['id'])
        for _ in range(REFRESH_BATCH):
            if self.dirty.empty(): break
            iid=await self.dirty.get()
            try: await self.refresh(iid)
            finally: await asyncio.sleep(WFM_REQUEST_DELAY)

    async def rest_loop(self):
        first=True
        while not self.stop.is_set():
            try:
                if first or not self._catalog_exists(): await self.catalog()
                first=False
                await self.recent_mark(); await self.batch()
            except Exception: log.exception('collector loop')
            await asyncio.sleep(RECENT_SYNC_SECONDS)

    def _catalog_exists(self):
        with db() as c:return c.execute('SELECT 1 FROM items LIMIT 1').fetchone() is not None

    async def ws_loop(self):
        payload={'route':'@wfm|cmd/subscribe/newOrders','id':str(uuid.uuid4()),'payload':{'platform':PLATFORM,'crossplay':CROSSPLAY}}
        while not self.stop.is_set():
            try:
                async with websockets.connect(WS_URL,ping_interval=20,ping_timeout=20,max_size=2**20) as ws:
                    await ws.send(json.dumps(payload)); log.info('WFM websocket connected')
                    async for msg in ws:
                        try:p=json.loads(msg)
                        except:continue
                        if p.get('route')=='@wfm|event/subscriptions/newOrder': self.mark(str((p.get('payload') or {}).get('itemId')))
            except Exception: log.exception('websocket'); await asyncio.sleep(10)

def item_name_safe(it):
    return it.get('i18n',{}).get('en',{}).get('name') or it.get('name') or it.get('slug','').replace('_',' ')
