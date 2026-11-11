"""`scenic-dmp serve [program.scenic | workspace.json]`: run the web app locally."""

import argparse
import json
import threading
import webbrowser
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="scenic-dmp", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the web app on localhost")
    serve.add_argument("target", nargs="?", help="a .scenic program or a saved workspace .json")
    serve.add_argument("--mode2D", action="store_true", help="compile the program in 2D mode")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", action="store_true", help="open the app in a browser")
    args = parser.parse_args(argv)

    import uvicorn

    from .server import AppError, AppState, create_app

    state = AppState()
    if args.target:
        target = Path(args.target).expanduser()
        try:
            if target.suffix == ".json":
                state.load_workspace(json.loads(target.read_text()))
            else:
                state.open_program(target, mode2D=args.mode2D)
        except (AppError, OSError, ValueError) as exc:
            parser.error(str(exc))
    elif args.mode2D:
        state.set_program(mode2D=True)

    url = f"http://{args.host}:{args.port}/"
    print(f"scenic-dmp: serving on {url}", flush=True)
    if args.open:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    uvicorn.run(create_app(state), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
