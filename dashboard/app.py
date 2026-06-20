from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
import requests
import os

dash = FastAPI(title="Mini Kubernetes Dashboard")

# Fix template path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

CONTAINERS_RUNNING = Gauge("mk8s_containers_running", "Total running containers")
NODES_HEALTHY = Gauge("mk8s_nodes_healthy", "Healthy node count")
DEPLOYMENTS_TOTAL = Gauge("mk8s_deployments_total", "Total deployments")


@dash.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        resp = requests.get("http://localhost:8000/status", timeout=2)
        data = resp.json()
        nodes = data.get("nodes", [])
        containers = data.get("containers", [])
        deployments = data.get("deployments", [])
        summary = data.get("summary", {})
    except Exception:
        nodes, containers, deployments, summary = [], [], [], {}

    CONTAINERS_RUNNING.set(
        sum(1 for c in containers if c.get("status") == "running"))
    NODES_HEALTHY.set(sum(1 for n in nodes if n.get("healthy")))
    DEPLOYMENTS_TOTAL.set(len(deployments))

    return templates.TemplateResponse("index.html", {
        "request": request,
        "nodes": nodes,
        "containers": containers,
        "deployments": deployments,
        "summary": summary
    })


@dash.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)