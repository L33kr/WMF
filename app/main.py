import asyncio, time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .db import init_db, db
from .config import HOST, PORT, HISTORY_RETENTION_DAYS
from .wfm import WFMClient
from .collector import Collector

client=WFMClient(); collector=Collector(client)

def spawn(coro):
    t=asyncio.create_task(coro); return t

@asynccontextmanager
async def lifespan(app):
    init_db(); tasks=[spawn(collector.rest_loop()),spawn(collector.ws_loop())]
    async def prune():
        while not collector.stop.is_set():
            with db() as c:c.execute('DELETE FROM price_history WHERE ts<?',(time.time()-HISTORY_RETENTION_DAYS*86400,))
            await asyncio.sleep(3600)
    tasks.append(spawn(prune()))
    yield
    collector.stop.set()
    for t in tasks:t.cancel()
    await client.close()

app=FastAPI(title='WFM Trader API',version='2.0.0',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parent.parent/'static'),name='static')

@app.get('/',include_in_schema=False)
def home():return FileResponse(Path(__file__).resolve().parent.parent/'static'/'index.html')

@app.get('/api/health')
def health():
    with db() as c:
        total=c.execute('SELECT COUNT(*) FROM items').fetchone()[0]; priced=c.execute('SELECT COUNT(*) FROM market').fetchone()[0]
    return {'ok':True,'items':total,'priced_items':priced,'time':time.time()}

@app.get('/api/stats')
def stats_api():
    with db() as c:
    r = c.execute('''
        SELECT
            COUNT(*) AS items,
            (SELECT COUNT(*) FROM market) AS priced,
            AVG(m.liquidity) AS avg_liquidity,
            MAX(m.updated_at) AS last_update
        FROM items i
        LEFT JOIN market m
            ON m.item_id = i.id
    ''').fetchone()
    return dict(r)

SORTS={'name':'i.name','min':'m.min_price','median':'m.median','roi':'CASE WHEN m.min_price>0 AND m.median IS NOT NULL THEN (m.median-m.min_price)/m.min_price ELSE NULL END','buy':'m.buy_max','sellers':'m.sellers','buyers':'m.buyers','liquidity':'m.liquidity','score':'m.score','updated':'m.updated_at'}

@app.get('/api/items')
def items(search:str='',min_price:float|None=None,max_price:float|None=None,min_roi:float|None=None,min_liquidity:float|None=None,sort:str='score',order:str='desc',page:int=1,page_size:int=100):
    page_size=max(1,min(500,page_size)); wh=['1=1']; args=[]
    if search: wh.append('(i.name LIKE ? OR i.slug LIKE ?)'); q=f'%{search}%'; args += [q,q]
    if min_price is not None:wh.append('m.min_price>=?');args.append(min_price)
    if max_price is not None:wh.append('m.min_price<=?');args.append(max_price)
    if min_liquidity is not None:wh.append('COALESCE(m.liquidity,0)>=?');args.append(min_liquidity)
    if min_roi is not None:wh.append('CASE WHEN m.min_price>0 AND m.median IS NOT NULL THEN (m.median-m.min_price)/m.min_price*100 ELSE -999 END>=?');args.append(min_roi)
    direction='ASC' if order.lower()=='asc' else 'DESC'; sort_sql=SORTS.get(sort,SORTS['score']); where=' AND '.join(wh)
    with db() as c:
        total=c.execute(f'SELECT COUNT(*) FROM items i LEFT JOIN market m ON m.item_id=i.id WHERE {where}',args).fetchone()[0]
        rows=c.execute(f'''SELECT i.id,i.slug,i.name,i.category,i.updated_at item_updated,m.min_price,m.median,m.avg_price,m.p25,m.p75,m.buy_max,m.sellers,m.buyers,m.liquidity,m.score,m.updated_at
        FROM items i LEFT JOIN market m ON m.item_id=i.id WHERE {where} ORDER BY {sort_sql} {direction},i.name LIMIT ? OFFSET ?''',args+[page_size,(page-1)*page_size]).fetchall()
    out=[]
    for r in rows:
        x=dict(r); x['roi']=round((x['median']-x['min_price'])/x['min_price']*100,1) if x['median'] and x['min_price'] else None; out.append(x)
    return {'total':total,'page':page,'page_size':page_size,'items':out}

@app.get('/api/items/{slug}')
def item(slug:str):
    with db() as c:
        r=c.execute('SELECT i.*,m.min_price,m.median,m.avg_price,m.p25,m.p75,m.buy_max,m.sellers,m.buyers,m.liquidity,m.score,m.updated_at market_updated FROM items i LEFT JOIN market m ON m.item_id=i.id WHERE i.slug=?',(slug,)).fetchone()
        if not r: raise HTTPException(404,'Item not found')
        h=c.execute('SELECT ts,min_price,median,buy_max,liquidity,score FROM price_history WHERE item_id=? ORDER BY ts DESC LIMIT 300',(r['id'],)).fetchall()
    return {'item':dict(r),'history':[dict(x) for x in reversed(h)]}

@app.post('/api/items/{slug}/refresh')
def refresh(slug:str):
    with db() as c:r=c.execute('SELECT id FROM items WHERE slug=?',(slug,)).fetchone()
    if not r:raise HTTPException(404,'Item not found')
    collector.mark(r['id']); return {'ok':True,'queued':True}

@app.get('/api/deals')
def deals(limit:int=100,min_roi:float=10,min_liquidity:float=50):
    with db() as c:rows=c.execute('''SELECT i.slug,i.name,m.min_price,m.median,m.buy_max,m.sellers,m.buyers,m.liquidity,m.score,m.updated_at FROM market m JOIN items i ON i.id=m.item_id WHERE m.min_price IS NOT NULL AND m.median IS NOT NULL AND m.liquidity>=? ORDER BY m.score DESC LIMIT ?''',(min_liquidity,limit)).fetchall()
    out=[]
    for r in rows:
        x=dict(r); roi=(x['median']-x['min_price'])/x['min_price']*100 if x['min_price'] else 0
        if roi>=min_roi:x['roi']=round(roi,1);out.append(x)
    return out
