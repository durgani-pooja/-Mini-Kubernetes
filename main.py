from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
import requests

dash = FastAPI(title="Mini Kubernetes Dashboard")

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

    CONTAINERS_RUNNING.set(sum(1 for c in containers if c.get("status") == "running"))
    NODES_HEALTHY.set(sum(1 for n in nodes if n.get("healthy")))
    DEPLOYMENTS_TOTAL.set(len(deployments))

    nodes_html = ""
    for n in nodes:
        dot = "🟢" if n.get("healthy") else "🔴"
        nodes_html += f"<tr><td>{n['id']}</td><td>{n['host']}</td><td>{n['port']}</td><td>{dot}</td><td>{n['container_count']}</td></tr>"

    containers_html = ""
    for c in containers:
        dot = "🟢" if c.get("status") == "running" else "🔴"
        containers_html += f"<tr><td>{c['id'][:12]}</td><td>{c['deployment']}</td><td>{c['node_id'][:12]}</td><td>{dot} {c['status']}</td></tr>"

    deployments_html = ""
    for d in deployments:
        deployments_html += f"<tr><td>{d['name']}</td><td>{d['image']}</td><td>{d['replicas']}</td><td>{d['status']}</td></tr>"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mini Kubernetes Dashboard</title>
        <meta http-equiv="refresh" content="5">
        <style>
            body {{ font-family: Segoe UI, sans-serif; background: #0f1117; color: #e2e8f0; margin: 0; padding: 0; }}
            header {{ background: #1a1d2e; padding: 1rem 2rem; border-bottom: 1px solid #2d3148; }}
            header h1 {{ color: #7c83fd; margin: 0; font-size: 1.4rem; }}
            .summary {{ display: flex; gap: 1rem; padding: 1.5rem 2rem; }}
            .stat {{ background: #1a1d2e; border: 1px solid #2d3148; border-radius: 10px; padding: 1rem 1.5rem; min-width: 120px; }}
            .stat .label {{ font-size: 11px; color: #64748b; text-transform: uppercase; margin-bottom: 4px; }}
            .stat .value {{ font-size: 28px; font-weight: 600; color: #7c83fd; }}
            .content {{ padding: 0 2rem 2rem; display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }}
            .section {{ background: #1a1d2e; border: 1px solid #2d3148; border-radius: 10px; overflow: hidden; }}
            .section h2 {{ background: #20243a; margin: 0; padding: .75rem 1.25rem; font-size: 13px; color: #a5b4fc; border-bottom: 1px solid #2d3148; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th {{ padding: 8px 1rem; font-size: 11px; color: #64748b; text-align: left; border-bottom: 1px solid #2d3148; text-transform: uppercase; }}
            td {{ padding: 10px 1rem; font-size: 13px; border-bottom: 1px solid #1e2235; font-family: monospace; }}
            tr:last-child td {{ border-bottom: none; }}
            tr:hover td {{ background: #20243a; }}
            .empty {{ padding: 2rem; text-align: center; color: #64748b; font-size: 13px; }}
            .full {{ grid-column: span 2; }}
            .refresh {{ font-size: 11px; color: #64748b; float: right; margin-top: 4px; }}
        </style>
    </head>
    <body>
    <header>
        <h1>⚙ Mini Kubernetes Dashboard <span class="refresh">Auto-refreshes every 5s</span></h1>
    </header>

    <div class="summary">
        <div class="stat"><div class="label">Total Nodes</div><div class="value">{summary.get('total_nodes', len(nodes))}</div></div>
        <div class="stat"><div class="label">Healthy Nodes</div><div class="value" style="color:#22c55e">{summary.get('healthy_nodes', 0)}</div></div>
        <div class="stat"><div class="label">Containers</div><div class="value">{summary.get('total_containers', len(containers))}</div></div>
        <div class="stat"><div class="label">Running</div><div class="value" style="color:#22c55e">{summary.get('running_containers', 0)}</div></div>
        <div class="stat"><div class="label">Deployments</div><div class="value">{len(deployments)}</div></div>
    </div>

    <div class="content">
        <div class="section">
            <h2>🖥 Nodes ({len(nodes)})</h2>
            {'<table><tr><th>ID</th><th>Host</th><th>Port</th><th>Status</th><th>Containers</th></tr>' + nodes_html + '</table>' if nodes else '<div class="empty">No nodes registered</div>'}
        </div>

        <div class="section">
            <h2>🚀 Deployments ({len(deployments)})</h2>
            {'<table><tr><th>Name</th><th>Image</th><th>Replicas</th><th>Status</th></tr>' + deployments_html + '</table>' if deployments else '<div class="empty">No deployments yet</div>'}
        </div>

        <div class="section full">
            <h2>📦 Containers ({len(containers)})</h2>
            {'<table><tr><th>Container ID</th><th>Deployment</th><th>Node</th><th>Status</th></tr>' + containers_html + '</table>' if containers else '<div class="empty">No containers running yet</div>'}
        </div>
    </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@dash.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)