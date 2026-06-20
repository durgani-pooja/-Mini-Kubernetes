Mini Kubernetes

A simplified container orchestration system built from scratch in Python — implementing the core concepts behind Kubernetes: scheduling, health-check-driven self-healing, and zero-downtime rolling deployments.

What it does

Mini Kubernetes manages a cluster of worker nodes and automatically:


Schedules containers across nodes based on current load
Monitors container health every 5 seconds and automatically replaces failed containers within 15 seconds
Rolls out updates one container at a time with automatic rollback if a new version fails health checks
Tracks cluster state — nodes, containers, and deployments — via a REST API and live dashboard


This mirrors the architecture of production-grade orchestrators (Kubernetes, Nomad) at a scale suitable for learning and demonstration.

Architecture

┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Client    │─────▶│  API Server  │─────▶│  Scheduler  │
│ (curl/docs) │      │  (FastAPI)   │      │             │
└─────────────┘      └──────┬───────┘      └──────┬──────┘
                             │                     │
                             ▼                     ▼
                      ┌──────────────┐      ┌─────────────┐
                      │ State Store  │◀────▶│   Docker    │
                      │  (SQLite)    │      │   Client    │
                      └──────┬───────┘      └─────────────┘
                             │
                             ▼
                      ┌──────────────┐
                      │   Health     │
                      │   Checker    │ (background thread, every 5s)
                      └──────────────┘

Key features

FeatureHow it worksSchedulingPicks the node with the fewest running containers (least-loaded strategy)Self-healingBackground thread checks every container every 5s; after 3 consecutive failures, automatically schedules a replacement on a healthy nodeRolling deploysReplaces containers one at a time — starts new container, waits for health check, then stops the old one. Automatically rolls back all changes if any health check failsLive dashboardAuto-refreshing web UI showing nodes, containers, and deployments in real timeREST APIFull CRUD on deployments via FastAPI, with interactive Swagger docs at /docs

Tech stack


Python — FastAPI, Uvicorn, Pydantic
Docker SDK — container lifecycle management
SQLite — cluster state persistence
Prometheus client — metrics export


Getting started

Prerequisites


Python 3.11
Docker Desktop (running)


Installation

bashgit clone https://github.com/YOUR_USERNAME/mini-kubernetes.git
cd mini-kubernetes
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Mac/Linux
pip install -r requirements.txt

Run

bashuvicorn core.api_server:app --host 0.0.0.0 --port 8000 --reload

Open:


API docs → http://localhost:8000/docs
Dashboard → http://localhost:8000/dashboard


Deploy your first container

bashcurl -X POST http://localhost:8000/deploy \
  -H "Content-Type: application/json" \
  -d '{"image": "nginx:latest", "replicas": 2, "name": "my-app"}'

Test self-healing

Stop one of the running containers manually in Docker Desktop. Within 15 seconds, the health checker detects the failure and starts a replacement automatically — check /status or the dashboard to confirm.

Test rolling updates

bashcurl -X PUT http://localhost:8000/deploy/my-app \
  -H "Content-Type: application/json" \
  -d '{"new_image": "nginx:1.25"}'

API reference

MethodEndpointDescriptionPOST/deployCreate a new deployment with N replicasGET/statusFull cluster state — nodes, containers, deploymentsGET/deploy/{name}Get a specific deployment's statusPUT/deploy/{name}Rolling update to a new imageDELETE/deploy/{name}Remove a deployment and its containersGET/nodesList all worker nodesPOST/nodesRegister a new worker nodeGET/healthService health check

What I learned building this


How leader-less, least-loaded scheduling works at a basic level
Why health checks need a failure threshold (not single-check) to avoid false positives from transient network blips
How rolling updates must start the new instance before stopping the old one to maintain availability
The tradeoffs between simplicity (SQLite, polling) and production-readiness (etcd, watch-based events) in real orchestrators


Future improvements


Resource-aware scheduling (CPU/memory based, not just container count)
Persistent volumes for stateful workloads
Multi-region node support
gRPC-based node agents instead of direct Docker SDK calls
