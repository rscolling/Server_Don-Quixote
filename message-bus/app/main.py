from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.database import init_db, close_db, set_on_change
from app.routes.system import broadcast_update
from app.routes import system, agents, messages, tasks, capabilities, subscriptions


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    set_on_change(broadcast_update)
    yield
    await close_db()


app = FastAPI(
    title="Message Bus",
    description="Multi-agent communication hub for don-quixote",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(agents.router)
app.include_router(messages.router)
app.include_router(tasks.router)
app.include_router(capabilities.router)
app.include_router(subscriptions.router)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})
