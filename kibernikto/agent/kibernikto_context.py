from typing import Callable, Optional, Dict, Any, Tuple
import asyncio

from kibernikto.agent.kibernikto_agent import KiberniktoAgent


def singleton(cls):
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


@singleton
class KiberniktoContext:
    def __init__(self):
        self._session_storage: Dict[str | int, dict] = {}
        self.agent_registries: Dict[str | int, KiberniktoAgent] = {}

    def add_call_session_data(self, session_key: str, label: str, data: Any) -> None:
        """
        Stores data in the session storage using the provided session key.
        :param session_key: Unique identifier for the session.
        :param data: Data to be stored.
        """
        if session_key in self._session_storage:
            self._session_storage[session_key][label] = data
        else:
            self._session_storage[session_key] = {label: data}

    def get_call_session_data(self, session_key: str) -> Optional[Any]:
        """
        Retrieves data from the session storage using the provided session key.
        :param session_key: Unique identifier for the session.
        :return: The stored data, or None if the session key does not exist.
        """
        return self._session_storage.get(session_key, {})

    def delete_call_session_data(self, session_key: str) -> None:
        """
        Deletes data from the session storage using the provided session key.
        :param session_key: Unique identifier for the session.
        """
        if session_key in self._session_storage:
            del self._session_storage[session_key]

    def get_task_delegate(self, key: str, agent_label: str):
        initiator = self.agent_registries.get(key)

        if not initiator:
            raise LookupError(f"No agent found for key: {key}")

        if agent_label:
            delegate = initiator.get_task_delegate(agent_label)
        else:
            delegate = None
        return initiator, delegate

    def register_agent(self, agent: KiberniktoAgent):
        self.agent_registries[agent.unique_id] = agent


kibernikto_context = KiberniktoContext()
