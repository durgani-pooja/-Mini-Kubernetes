"""SQLite-backed cluster state store for Mini Kubernetes."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class Node:
    id: str
    host: str
    port: int
    healthy: bool
    container_count: int


@dataclass
class Container:
    id: str
    node_id: str
    deployment: str
    status: str


@dataclass
class Deployment:
    name: str
    image: str
    replicas: int
    status: str


class StateStore:
    """Thread-safe SQLite store for nodes, containers, and deployments."""

    def __init__(self, db_path: str = "cluster.db") -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    healthy INTEGER NOT NULL DEFAULT 1,
                    container_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS deployments (
                    name TEXT PRIMARY KEY,
                    image TEXT NOT NULL,
                    replicas INTEGER NOT NULL,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS containers (
                    id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    deployment TEXT NOT NULL,
                    status TEXT NOT NULL,
                    FOREIGN KEY (node_id) REFERENCES nodes(id),
                    FOREIGN KEY (deployment) REFERENCES deployments(name)
                );
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        return Node(
            id=row["id"],
            host=row["host"],
            port=row["port"],
            healthy=bool(row["healthy"]),
            container_count=row["container_count"],
        )

    @staticmethod
    def _row_to_container(row: sqlite3.Row) -> Container:
        return Container(
            id=row["id"],
            node_id=row["node_id"],
            deployment=row["deployment"],
            status=row["status"],
        )

    @staticmethod
    def _row_to_deployment(row: sqlite3.Row) -> Deployment:
        return Deployment(
            name=row["name"],
            image=row["image"],
            replicas=row["replicas"],
            status=row["status"],
        )

    def register_node(self, node: Node) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO nodes (id, host, port, healthy, container_count)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    host = excluded.host,
                    port = excluded.port,
                    healthy = excluded.healthy,
                    container_count = excluded.container_count
                """,
                (
                    node.id,
                    node.host,
                    node.port,
                    int(node.healthy),
                    node.container_count,
                ),
            )
            self._conn.commit()

    def get_all_nodes(self) -> list[Node]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, host, port, healthy, container_count FROM nodes ORDER BY id"
            ).fetchall()
        return [self._row_to_node(row) for row in rows]

    def set_node_health(self, node_id: str, healthy: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE nodes SET healthy = ? WHERE id = ?",
                (int(healthy), node_id),
            )
            self._conn.commit()

    def register_container(self, cid: str, node_id: str, deployment: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO containers (id, node_id, deployment, status)
                VALUES (?, ?, ?, 'running')
                """,
                (cid, node_id, deployment),
            )
            self._conn.execute(
                """
                UPDATE nodes
                SET container_count = container_count + 1
                WHERE id = ?
                """,
                (node_id,),
            )
            self._conn.commit()

    def get_all_containers(self) -> list[Container]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, node_id, deployment, status FROM containers ORDER BY id"
            ).fetchall()
        return [self._row_to_container(row) for row in rows]

    def get_containers_by_deployment(self, name: str) -> list[Container]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, node_id, deployment, status
                FROM containers
                WHERE deployment = ?
                ORDER BY id
                """,
                (name,),
            ).fetchall()
        return [self._row_to_container(row) for row in rows]

    def mark_container_dead(self, cid: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE containers SET status = 'dead' WHERE id = ?",
                (cid,),
            )
            self._conn.commit()

    def remove_container(self, cid: str) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT node_id FROM containers WHERE id = ?",
                (cid,),
            ).fetchone()
            if row is None:
                return

            node_id = row["node_id"]
            self._conn.execute("DELETE FROM containers WHERE id = ?", (cid,))
            self._conn.execute(
                """
                UPDATE nodes
                SET container_count = MAX(container_count - 1, 0)
                WHERE id = ?
                """,
                (node_id,),
            )
            self._conn.commit()

    def create_deployment(self, name: str, image: str, replicas: int) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO deployments (name, image, replicas, status)
                VALUES (?, ?, ?, 'active')
                """,
                (name, image, replicas),
            )
            self._conn.commit()

    def get_deployment(self, name: str) -> Optional[Deployment]:
        with self._lock:
            row = self._conn.execute(
                "SELECT name, image, replicas, status FROM deployments WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_deployment(row)

    def get_all_deployments(self) -> list[Deployment]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, image, replicas, status FROM deployments ORDER BY name"
            ).fetchall()
        return [self._row_to_deployment(row) for row in rows]

    def remove_deployment(self, name: str) -> None:
        with self._lock:
            containers = self._conn.execute(
                "SELECT id, node_id FROM containers WHERE deployment = ?",
                (name,),
            ).fetchall()

            for container in containers:
                self._conn.execute(
                    "DELETE FROM containers WHERE id = ?",
                    (container["id"],),
                )
                self._conn.execute(
                    """
                    UPDATE nodes
                    SET container_count = MAX(container_count - 1, 0)
                    WHERE id = ?
                    """,
                    (container["node_id"],),
                )

            self._conn.execute("DELETE FROM deployments WHERE name = ?", (name,))
            self._conn.commit()

    def update_deployment_image(self, name: str, new_image: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE deployments SET image = ? WHERE name = ?",
                (new_image, name),
            )
            self._conn.commit()

    def get_node_for_container(self, cid: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT node_id FROM containers WHERE id = ?",
                (cid,),
            ).fetchone()
        if row is None:
            return None
        return row["node_id"]
