import threading, webbrowser, uvicorn
if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8000")).start()
    uvicorn.run("api.server:app", host="127.0.0.1", port=8000)
