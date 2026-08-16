import math
import statistics
import httpx
from .config import API_BASE

class WFMClient:
    def __init__(self):
        self.http = httpx.AsyncClient(base_url=API_BASE, timeout=20, headers={'Accept':'application/json'})
    async def close(self):
        await self.http.aclose()
    async def get(self, path):
        r = await self.http.get(path)
        r.raise_for_status()
        j = r.json()
        if j.get('error'):
            raise RuntimeError(str(j['error']))
        return j.get('data', j)
    async def items(self):
        d = await self.get('/items')
        return d if isinstance(d, list) else d.get('items', [])
    async def recent(self):
        d = await self.get('/orders/recent')
        return d if isinstance(d, list) else d.get('orders', [])
    async def item_orders(self, slug):
        d = await self.get('/orders/item/' + slug)
        return d if isinstance(d, list) else d.get('orders', [])

def item_name(item):
    return item.get('i18n',{}).get('en',{}).get('name') or item.get('name') or item.get('slug','').replace('_',' ')

def normalize(order, item=None):
    it = order.get('item') or item or {}
    user = order.get('user') or {}
    p = order.get('platinum', 0)
    q = order.get('quantity', 1)
    try: p = float(p)
    except: p = 0.0
    try: q = int(q)
    except: q = 1
    status = str(user.get('status') or '').lower()
    return {
      'id': order.get('id'), 'item_id': order.get('itemId') or it.get('id'),
      'slug': it.get('slug') or order.get('slug') or '',
      'name': item_name(it) if it else '',
      'type': str(order.get('type') or 'sell').lower(),
      'platinum': max(0.0,p), 'quantity': max(1,q),
      'online': user.get('online') is True or 'online' in status or 'ingame' in status,
      'user': user.get('ingameName') or user.get('slug') or '?'
    }

def stats(orders):
    sells = [o for o in orders if o['type']=='sell' and o['platinum']>0]
    buys = [o for o in orders if o['type']=='buy' and o['platinum']>0]
    sp = sorted(o['platinum'] for o in sells)
    bp = [o['platinum'] for o in buys]
    if sp:
        med = statistics.median(sp)
        p25 = sp[max(0, math.floor((len(sp)-1)*.25))]
        p75 = sp[min(len(sp)-1, math.ceil((len(sp)-1)*.75))]
        avg = statistics.fmean(sp)
        mn = sp[0]
    else:
        med=p25=p75=avg=mn=None
    bmax = max(bp) if bp else None
    sq = sum(o['quantity'] for o in sells); bq = sum(o['quantity'] for o in buys)
    depth = min(100, math.log10(1+sq+bq)*25)
    demand = min(100, len(buys)*10)
    stability = 40
    if len(sp)>=5 and med:
        dev = statistics.fmean(abs(x-med) for x in sp)
        stability = max(0,min(100,100-(dev/med)*300))
    liq = round(min(100, depth*.25+demand*.45+stability*.30),1)
    score = round(min(100, max(0, ((med-mn)/med*100 if med and mn else 0)*.6 + liq*.4)),1) if med and mn else None
    return {'min_price':mn,'median':med,'avg_price':avg,'p25':p25,'p75':p75,'buy_max':bmax,'sellers':len(sells),'buyers':len(buys),'seller_qty':sq,'buyer_qty':bq,'liquidity':liq,'score':score}
