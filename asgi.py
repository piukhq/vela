import uvicorn

from vela import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("asgi:app", port=8001, reload=False)
