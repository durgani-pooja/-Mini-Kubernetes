"""Background health monitoring and automatic rescheduling for Mini Kubernetes."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import Optional

from core.scheduler import Scheduler
from core.state_store import Container, Node, StateStore
from node.docker_client import DockerClient


class HealthChecker:
    """Monitors container and node health, rescheduling failed workloads."""

    MAX_FAILS = 3

    def __init__(self, store: StateStore, interval: int = 5) -> None:
        self.store = store
        self.interval = interval
        self.fail_counts: defaultdict[str, int] = defaultdict(int)
        self._docker = DockerClient()
        self.scheduler = Scheduler(store, self._docker)

    def _docker_for_node(self, node: Node) -> DockerClient:
        if node.host in ("localhost", "127.0.0.1", "0.0.0.0"):
            return self._docker
        return DockerClient(base_url=f"tcp://{node.host}:{node.port}")

    def _get_node(self, node_id: str) -> Optional[Node]:
        for node in self.store.get_all_nodes():
            if node.id == node_id:
                return node
        return None

    def run(self) -> None:
        """Run health checks in an infinite loop."""
        print(f"[health] Health checker started (interval={self.interval}s)")
        while True:
            try:
                self.check_all_containers()
                self.check_all_nodes()
            except Exception as exc:
                print(f"[health] Unexpected error in health loop: {exc}")
            time.sleep(self.interval)

    def check_all_containers(self) -> None:
        """Check every tracked container and handle failures."""
        try:
            containers = self.store.get_all_containers()
        except Exception as exc:
            print(f"[health] Failed to load containers: {exc}")
            return

        for container in containers:
            try:
                if container.status == "dead":
                    continue

                node = self._get_node(container.node_id)
                if node is None:
                    print(
                        f"[health] Container {container.id[:12]} has unknown node "
                        f"'{container.node_id}' — treating as failure"
                    )
                    self._handle_failure(container)
                    continue

                docker = self._docker_for_node(node)
                status = docker.get_status(container.id)

                if status == "running":
                    self.fail_counts.pop(container.id, None)
                    continue

                print(
                    f"[health] Container {container.id[:12]} not running "
                    f"(status={status})"
                )
                self._handle_failure(container)
            except Exception as exc:
                print(
                    f"[health] Error checking container {container.id[:12]}: {exc}"
                )

    def _handle_failure(self, container: Container) -> None:
        """Track consecutive failures and reschedule after MAX_FAILS."""
        try:
            self.fail_counts[container.id] += 1
            count = self.fail_counts[container.id]
            print(
                f"[health] Container {container.id[:12]} failure "
                f"{count}/{self.MAX_FAILS}"
            )

            if count < self.MAX_FAILS:
                return

            print(
                f"[health] container {container.id[:12]} declared dead - rescheduling"
            )
            self.store.mark_container_dead(container.id)
            self.fail_counts.pop(container.id, None)
            self._reschedule(container)
        except Exception as exc:
            print(
                f"[health] Error handling failure for {container.id[:12]}: {exc}"
            )

    def _reschedule(self, dead_container: Container) -> None:
        """Start a replacement container on a healthy node."""
        try:
            deployment = self.store.get_deployment(dead_container.deployment)
            if deployment is None:
                print(
                    f"[health] Cannot reschedule {dead_container.id[:12]}: "
                    f"deployment '{dead_container.deployment}' not found"
                )
                self.store.remove_container(dead_container.id)
                return

            node = self.scheduler.pick_node()
            if node is None:
                print(
                    f"[health] Cannot reschedule {dead_container.id[:12]}: "
                    "no healthy nodes available"
                )
                return

            old_node = self._get_node(dead_container.node_id)
            if old_node is not None:
                self._docker_for_node(old_node).stop_container(dead_container.id)

            name = f"{dead_container.deployment}-{uuid.uuid4().hex[:8]}"
            docker = self._docker_for_node(node)
            new_id = docker.run_container(deployment.image, name, node)

            if not new_id:
                print(
                    f"[health] Failed to start replacement for "
                    f"{dead_container.id[:12]} on node '{node.id}'"
                )
                return

            self.store.remove_container(dead_container.id)
            self.store.register_container(new_id, node.id, dead_container.deployment)
            print(
                f"[health] Rescheduled {dead_container.id[:12]} -> "
                f"{new_id[:12]} on node '{node.id}'"
            )
        except Exception as exc:
            print(
                f"[health] Error rescheduling {dead_container.id[:12]}: {exc}"
            )

    def check_all_nodes(self) -> None:
        """Ping each node's Docker daemon and update health status."""
        try:
            nodes = self.store.get_all_nodes()
        except Exception as exc:
            print(f"[health] Failed to load nodes: {exc}")
            return

        for node in nodes:
            try:
                healthy = self._ping_node(node)
                if healthy != node.healthy:
                    self.store.set_node_health(node.id, healthy)
                    state = "healthy" if healthy else "unhealthy"
                    print(f"[health] Node '{node.id}' marked {state}")
                elif not healthy:
                    print(f"[health] Node '{node.id}' still unreachable")
            except Exception as exc:
                print(f"[health] Error checking node '{node.id}': {exc}")
                try:
                    self.store.set_node_health(node.id, False)
                except Exception as store_exc:
                    print(
                        f"[health] Failed to mark node '{node.id}' unhealthy: "
                        f"{store_exc}"
                    )

    def _ping_node(self, node: Node) -> bool:
        """Return True if the node's Docker daemon responds to ping."""
        try:
            client = self._docker_for_node(node)
            client._client.ping()
            return True
        except Exception:
            return False
