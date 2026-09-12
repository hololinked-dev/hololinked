from dataclasses import dataclass

from hololinked.server import stop
from hololinked.server.server import _runs


def stop_all_runs() -> None:
    """Stop every run."""
    for run_id in list(_runs):
        stop(run_id)


@dataclass
class AppIDs:
    """
    Application related IDs generally used by end-user,
    like server, client, and thing IDs.
    """

    server_id: str
    """RPC server ID"""
    client_id: str
    """A client ID"""
    thing_id: str
    """A thing ID"""
