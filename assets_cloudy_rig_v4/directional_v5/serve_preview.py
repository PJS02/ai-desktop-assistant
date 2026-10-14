"""Loopback-only standalone preview, with validated PNG export into exports/."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from io import BytesIO
from urllib.parse import urlsplit,parse_qs
import json,re
from PIL import Image

ROOT=Path(__file__).resolve().parent
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT.parent),**kwargs)
    def do_POST(self):
        url=urlsplit(self.path)
        name=parse_qs(url.query).get('name',[''])[0]
        if url.path!='/directional_v5/export-png' or not re.fullmatch(r'cloudy-[a-z0-9-]+\.png',name):
            self.send_error(400);return
        origin=self.headers.get('Origin','')
        if origin!='http://127.0.0.1:8771':
            self.send_error(403);return
        size=int(self.headers.get('Content-Length','0'))
        if not 0<size<24000000:
            self.send_error(413);return
        data=self.rfile.read(size)
        try:
            im=Image.open(BytesIO(data))
            assert im.format=='PNG' and im.size in [(720,1080),(4320,3240),(4320,2160)]
            im.load()
        except Exception:
            self.send_error(400,'Invalid PNG');return
        folder=ROOT/'exports';folder.mkdir(exist_ok=True)
        (folder/name).write_bytes(data)
        reply=json.dumps({'file':'exports/'+name,'bytes':len(data)}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(reply)));self.end_headers();self.wfile.write(reply)

if __name__=='__main__':
    ThreadingHTTPServer(('127.0.0.1',8771),Handler).serve_forever()
