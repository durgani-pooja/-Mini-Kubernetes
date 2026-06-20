"""Docker SDK wrapper for Mini Kubernetes node agents."""

from __future__ import annotations

import logging
from typing import Any, Optional

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

logger = logging.getLogger(__name__)

MANAGED_LABEL = "managed-by=mini-k8s"


class DockerClient:
    """Wraps the Docker SDK for running and managing cluster containers."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        try:
            if base_url:
                self._client = docker.DockerClient(base_url=base_url)
            else:
                self._client = docker.from_env()
        except DockerException as exc:
            logger.error("Failed to connect to Docker: %s", exc)
            raise

    def close(self) -> None:
        try:
            self._client.close()
        except DockerException as exc:
            logger.warning("Error closing Docker client: %s", exc)

    def run_container(self, image: str, name: str, node: Any) -> str:
        """Pull (if needed), start a container, and return its ID."""
        labels = {
            "managed-by": "mini-k8s",
            "node-id": getattr(node, "id", str(node)),
        }
        try:
            container = self._client.containers.run(
                image,
                name=name,
                detach=True,
                labels=labels,
                environment={"MINI_K8S_NODE": labels["node-id"]},
            )
            return container.id
        except ImageNotFound:
            logger.error("Image not found: %s", image)
        except DockerException as exc:
            logger.error("Failed to run container %s from %s: %s", name, image, exc)
        return ""

    def stop_container(self, cid: str) -> None:
        """Stop and remove a container, ignoring missing containers."""
        try:
            container = self._client.containers.get(cid)
            container.stop(timeout=10)
            container.remove()
        except NotFound:
            logger.debug("Container %s not found during stop", cid)
        except DockerException as exc:
            logger.error("Failed to stop container %s: %s", cid, exc)

    def get_status(self, cid: str) -> str:
        """Return container status as 'running', 'exited', or 'dead'."""
        try:
            container = self._client.containers.get(cid)
            status = container.status
            if status in ("running", "restarting"):
                return "running"
            if status == "dead":
                return "dead"
            return "exited"
        except NotFound:
            logger.debug("Container %s not found", cid)
            return "dead"
        except DockerException as exc:
            logger.error("Failed to get status for %s: %s", cid, exc)
            return "dead"

    def list_managed(self) -> list[dict[str, str]]:
        """Return all containers labeled managed-by=mini-k8s."""
        try:
            containers = self._client.containers.list(
                all=True,
                filters={"label": MANAGED_LABEL},
            )
            return [
                {
                    "id": container.id,
                    "name": container.name,
                    "status": container.status,
                    "image": container.image.tags[0] if container.image.tags else "",
                }
                for container in containers
            ]
        except DockerException as exc:
            logger.error("Failed to list managed containers: %s", exc)
            return []

    def get_stats(self, cid: str) -> dict[str, float]:
        """Return CPU and memory usage percentages for a container."""
        try:
            container = self._client.containers.get(cid)
            stats = container.stats(stream=False)
            return {
                "cpu_percent": self._calc_cpu_percent(stats),
                "mem_percent": self._calc_mem_percent(stats),
            }
        except NotFound:
            logger.debug("Container %s not found for stats", cid)
        except DockerException as exc:
            logger.error("Failed to get stats for %s: %s", cid, exc)
        return {"cpu_percent": 0.0, "mem_percent": 0.0}

    @staticmethod
    def _calc_cpu_percent(stats: dict[str, Any]) -> float:
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})
        try:
            cpu_usage = cpu_stats["cpu_usage"]["total_usage"]
            precpu_usage = precpu_stats["cpu_usage"]["total_usage"]
            system_usage = cpu_stats["system_cpu_usage"]
            presystem_usage = precpu_stats["system_cpu_usage"]
            cpu_delta = cpu_usage - precpu_usage
            system_delta = system_usage - presystem_usage
            if system_delta <= 0:
                return 0.0
            online_cpus = cpu_stats.get("online_cpus") or len(
                cpu_stats.get("cpu_usage", {}).get("percpu_usage") or [1]
            )
            return (cpu_delta / system_delta) * online_cpus * 100.0
        except (KeyError, TypeError, ZeroDivisionError):
            return 0.0

    @staticmethod
    def _calc_mem_percent(stats: dict[str, Any]) -> float:
        mem_stats = stats.get("memory_stats", {})
        try:
            usage = mem_stats["usage"]
            limit = mem_stats["limit"]
            if limit <= 0:
                return 0.0
            return (usage / limit) * 100.0
        except (KeyError, TypeError, ZeroDivisionError):
            return 0.0
