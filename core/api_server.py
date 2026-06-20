from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from core.state_store import StateStore, Node
from core.scheduler import Scheduler
from core.rolling_deploy import RollingDeployer
from node.docker_client import DockerClient

app = FastAPI(title="Mini Kubernetes API", version="1.0.0")
store = StateStore()
scheduler = Scheduler(store)
docker = DockerClient()
deployer = RollingDeployer(store)


class DeployRequest(BaseModel):
    image: str
    replicas: int
    name: str
    port: int = 80


class UpdateRequest(BaseModel):
    new_image: str


class NodeRequest(BaseModel):
    id: str
    host: str
    port: int


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mini-kubernetes"}


@app.post("/deploy")
async def deploy(req: DeployRequest):
    store.create_deployment(req.name, req.image, req.replicas)
    containers_started = []
    for i in range(req.replicas):
        node = scheduler.pick_node()
        if not node:
            raise HTTPException(503, "No healthy nodes available")
        try:
            cid = docker.run_container(
                image=req.image, name=f"{req.name}-{i}", node=node)
            store.register_container(cid, node.id, req.name)
            containers_started.append(cid[:12])
        except Exception as e:
            raise HTTPException(500, str(e))
    return {"status": "deployed", "deployment": req.name,
            "replicas": req.replicas, "containers": containers_started}


@app.get("/status")
async def status():
    nodes = store.get_all_nodes()
    containers = store.get_all_containers()
    deployments = store.get_all_deployments()
    return {
        "nodes": [vars(n) for n in nodes],
        "containers": [vars(c) for c in containers],
        "deployments": [vars(d) for d in deployments],
        "summary": {
            "total_nodes": len(nodes),
            "healthy_nodes": sum(1 for n in nodes if n.healthy),
            "total_containers": len(containers),
            "running_containers": sum(1 for c in containers if c.status == "running"),
            "total_deployments": len(deployments)
        }
    }


@app.get("/deploy/{name}")
async def get_deployment(name: str):
    d = store.get_deployment(name)
    if not d:
        raise HTTPException(404, f"Deployment '{name}' not found")
    return {"deployment": vars(d),
            "containers": store.get_containers_by_deployment(name)}


@app.put("/deploy/{name}")
async def update_deployment(name: str, req: UpdateRequest):
    if not store.get_deployment(name):
        raise HTTPException(404, f"Deployment '{name}' not found")
    return deployer.update(name, req.new_image)


@app.delete("/deploy/{name}")
async def delete_deployment(name: str):
    if not store.get_deployment(name):
        raise HTTPException(404, f"Deployment '{name}' not found")
    containers = store.get_containers_by_deployment(name)
    for cid in containers:
        docker.stop_container(cid)
        store.remove_container(cid)
    store.remove_deployment(name)
    return {"status": "deleted", "deployment": name,
            "containers_removed": len(containers)}


@app.post("/nodes")
async def register_node(req: NodeRequest):
    node = Node(id=req.id, host=req.host, port=req.port)
    store.register_node(node)
    return {"status": "registered", "node": vars(node)}


@app.get("/nodes")
async def list_nodes():
    return {"nodes": [vars(n) for n in store.get_all_nodes()]}