#!/usr/bin/env python3
"""Serve this downloaded map using only Python's standard library."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    with ThreadingHTTPServer(('127.0.0.1',args.port),partial(SimpleHTTPRequestHandler,directory=str(root))) as server:
        url=f'http://127.0.0.1:{server.server_port}/'
        print(f'Energy network map: {url}\nPress Ctrl+C to stop.',flush=True)
        if not args.no_browser:webbrowser.open(url)
        try:server.serve_forever()
        except KeyboardInterrupt:pass

if __name__=='__main__':main()
