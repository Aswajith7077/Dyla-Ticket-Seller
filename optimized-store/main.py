from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.router import tickets, health
from app import state as app_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    await app_state.get_redis()
    yield


app = FastAPI(title="Optimized Ticket Store", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(tickets.router)
app.include_router(health.router)

if __name__ == "__main__":
    import uvicorn, os
    from dotenv import load_dotenv

    load_dotenv()
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
