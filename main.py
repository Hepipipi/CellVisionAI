"""Start the CellVision local web app using the project's standard entry point."""
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer

from web_app import HOST, PORT, Handler, init_db, load_ai_model


if __name__ == "__main__":
    init_db()
    import web_app
    web_app.AI_MODEL, web_app.AI_CLASSES = load_ai_model()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"CellVision web app: {url}\nНажмите Ctrl+C в этом окне для остановки.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")
        server.server_close()
