"""Placement scheduler for Mini Kubernetes."""

from __future__ import annotations

from typing import Optional

from core.state_store import Node, StateStore
from node.docker_client import DockerClient


class Scheduler:
    """Selects nodes for container placement using load and resource metrics."""

    def __init__(
        self,
        store: StateStore,
        docker_client: Optional[DockerClient] = None,
    ) -> None:
        self.store = store
        self._docker = docker_client or DockerClient()

    def _healthy_nodes(self) -> list[Node]:
        return [node for node in self.store.get_all_nodes() if node.healthy]

    def _running_on_node(self, node_id: str) -> list:
        return [
            container
            for container in self.store.get_all_containers()
            if container.node_id == node_id and container.status == "running"
        ]

    def _docker_for_node(self, node: Node) -> DockerClient:
        if node.host in ("localhost", "127.0.0.1", "0.0.0.0"):
            return self._docker
        return DockerClient(base_url=f"tcp://{node.host}:{node.port}")

    def pick_node(self) -> Optional[Node]:
        """Return the healthy node with the fewest running containers."""
        healthy = self._healthy_nodes()
        if not healthy:
            print("[Scheduler] No healthy nodes available — cannot pick a node")
            return None

        selected = min(
            healthy,
            key=lambda node: (len(self._running_on_node(node.id)), node.id),
        )
        running_count = len(self._running_on_node(selected.id))
        print(
            f"[Scheduler] Selected node '{selected.id}' "
            f"(reason: fewest running containers — {running_count})"
        )
        return selected

    def pick_node_resource_aware(self) -> Optional[Node]:
        """Return the healthy node with the lowest average CPU usage."""
        healthy = self._healthy_nodes()
        if not healthy:
            print("[Scheduler] No healthy nodes available — cannot pick a node")
            return None

        best_node: Optional[Node] = None
        best_avg_cpu = float("inf")

        for node in healthy:
            running = self._running_on_node(node.id)
            if not running:
                avg_cpu = 0.0
            else:
                docker = self._docker_for_node(node)
                total_cpu = sum(
                    docker.get_stats(container.id)["cpu_percent"]
                    for container in running
                )
                avg_cpu = total_cpu / len(running)

            if avg_cpu < best_avg_cpu or (
                avg_cpu == best_avg_cpu
                and (best_node is None or node.id < best_node.id)
            ):
                best_avg_cpu = avg_cpu
                best_node = node

        if best_node is not None:
            print(
                f"[Scheduler] Selected node '{best_node.id}' "
                f"(reason: lowest average CPU usage — {best_avg_cpu:.2f}%)"
            )
        return best_node

    def get_node_stats(self, node: Node) -> dict[str, dict[str, float]]:
        """Return per-container CPU and memory stats for all running containers on a node."""
        docker = self._docker_for_node(node)
        name_by_id = {
            entry["id"]: entry["name"] for entry in docker.list_managed()
        }

        stats: dict[str, dict[str, float]] = {}
        for container in self._running_on_node(node.id):
            name = name_by_id.get(
                container.id,
                f"{container.deployment}-{container.id[:12]}",
            )
            usage = docker.get_stats(container.id)
            stats[name] = {
                "cpu": usage["cpu_percent"],
                "mem": usage["mem_percent"],
            }
        return stats
