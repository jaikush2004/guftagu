from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"namastey dosto"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/hello/{name}")
def hello(name: str):
    return {"message": f"Namaste {name}!"}