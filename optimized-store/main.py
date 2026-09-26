import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.router import tickets, health, debug
from app.router.tickets import run_expiry_sweep
from app import state as app_state


async def process_expirations():
    while True:
        await asyncio.sleep(5)
        try:
            r = await app_state.get_redis()
            await run_expiry_sweep(r)
        except Exception:
            pass  # never crash the background task


@asynccontextmanager
async def lifespan(app: FastAPI):
    await app_state.get_redis()
    task = asyncio.create_task(process_expirations())
    yield
    task.cancel()


app = FastAPI(title="Optimized Ticket Store", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(tickets.router)
app.include_router(health.router)
app.include_router(debug.router)

if __name__ == "__main__":
    import uvicorn, os
    from dotenv import load_dotenv

    load_dotenv()
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
