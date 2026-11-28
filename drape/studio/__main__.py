import argparse

from .server import serve


def main():
    ap = argparse.ArgumentParser(prog="python -m drape.studio", description="Spunfection Studio (runs locally; the code package is drape)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    ap.add_argument("--share", action="store_true",
                    help="let other devices on your home network use it (phones, another computer)")
    ap.add_argument("--host", default=None, help="address to listen on (default 127.0.0.1: this computer only)")
    ap.add_argument("--http", action="store_true",
                    help="with --share: plain http (no certificate warning, but no live mode on other devices)")
    a = ap.parse_args()
    host = a.host or ("0.0.0.0" if a.share else "127.0.0.1")
    serve(a.port, open_browser=not a.no_browser, host=host, https=host != "127.0.0.1" and not a.http)


if __name__ == "__main__":
    main()
