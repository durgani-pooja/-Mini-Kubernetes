import time
from core.state_store import StateStore
from node.docker_client import DockerClient
from core.scheduler import Scheduler


class RollingDeployer:
    def __init__(self, store: StateStore):
        self.store = store
        self.docker = DockerClient()
        self.scheduler = Scheduler(store)

    def update(self, deployment_name: str, new_image: str) -> dict:
        """
        Rolling update — replaces containers one at a time.
        Rolls back everything if any health check fails.
        """
        deployment = self.store.get_deployment(deployment_name)
        if not deployment:
            return {"status": "error", "message": f"deployment {deployment_name} not found"}

        containers = self.store.get_containers_by_deployment(deployment_name)
        if not containers:
            return {"status": "error", "message": "no containers found for this deployment"}

        print(f"[deploy] starting rolling update: {deployment.image} → {new_image}")
        updated = []

        for old_cid in containers:
            node = self.store.get_node_for_container(old_cid)
            if not node:
                print(f"[deploy] no node found for {old_cid[:8]} — skipping")
                continue

            # step 1 — start new container with new image
            try:
                new_cid = self.docker.run_container(
                    image=new_image,
                    name=f"{deployment_name}-new-{len(updated)}",
                    node=node
                )
                print(f"[deploy] started {new_cid[:8]} with {new_image} on {node.id}")
            except Exception as e:
                print(f"[deploy] failed to start new container: {e}")
                self._rollback(updated, deployment.image)
                return {"status": "rolled_back", "reason": str(e)}

            # step 2 — wait for new container to become healthy
            if self._wait_healthy(new_cid, timeout=30):
                # step 3 — stop old container only after new one is healthy
                self.docker.stop_container(old_cid)
                self.store.remove_container(old_cid)
                self.store.register_container(new_cid, node.id, deployment_name)
                updated.append(new_cid)
                print(f"[deploy] replaced {old_cid[:8]} → {new_cid[:8]}")
            else:
                # health check failed — rollback everything
                print(f"[deploy] health check failed for {new_cid[:8]} — rolling back")
                self.docker.stop_container(new_cid)
                self._rollback(updated, deployment.image)
                return {
                    "status": "rolled_back",
                    "reason": "health check timeout",
                    "failed_container": new_cid
                }

        # all containers updated successfully
        self.store.update_deployment_image(deployment_name, new_image)
        print(f"[deploy] rolling update complete — {len(updated)} containers updated")
        return {
            "status": "success",
            "updated": len(updated),
            "new_image": new_image
        }

    def _wait_healthy(self, cid: str, timeout: int = 30) -> bool:
        """
        Poll container status every second.
        Returns True if running within timeout, False otherwise.
        """
        print(f"[deploy] waiting for {cid[:8]} to become healthy...")
        for i in range(timeout):
            status = self.docker.get_status(cid)
            if status == "running":
                print(f"[deploy] {cid[:8]} is healthy after {i + 1}s")
                return True
            time.sleep(1)
        print(f"[deploy] {cid[:8]} did not become healthy within {timeout}s")
        return False

    def _rollback(self, updated_cids: list, old_image: str):
        """
        Replace all newly updated containers back to the old image.
        Called automatically when any health check fails.
        """
        if not updated_cids:
            print("[rollback] nothing to roll back")
            return

        print(f"[rollback] rolling back {len(updated_cids)} containers to {old_image}")
        for cid in updated_cids:
            node = self.store.get_node_for_container(cid)
            if not node:
                print(f"[rollback] no node found for {cid[:8]} — skipping")
                continue
            try:
                # stop the new container
                self.docker.stop_container(cid)
                self.store.remove_container(cid)

                # restart old image on same node
                old_cid = self.docker.run_container(
                    image=old_image,
                    name=f"rollback-{len(updated_cids)}",
                    node=node
                )
                self.store.register_container(old_cid, node.id, "rollback")
                print(f"[rollback] restored {old_cid[:8]} on {node.id}")
            except Exception as e:
                print(f"[rollback] failed to restore on {node.id}: {e}")