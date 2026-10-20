"""Camada de persistência.

Interface mínima (get/create/replace/delete por id) com duas implementações:
- CosmosStore: Azure Cosmos DB (produção)
- MemoryStore: em memória (testes automatizados)

Todos os containers usam chave de partição /id, então toda operação é uma
leitura/escrita pontual (barata), sem consultas entre partições.
"""
import copy
import time

from .logs import log_event


class ConflictError(Exception):
    """Já existe um documento com este id."""


class StoreError(Exception):
    """Falha de infraestrutura no banco."""


class MemoryStore:
    def __init__(self, clock=time.time):
        self._data = {}
        self._clock = clock

    def _alive(self, doc):
        ttl = doc.get("ttl")
        return not (isinstance(ttl, int) and ttl > 0 and self._clock() > doc["_created"] + ttl)

    def get(self, container, doc_id):
        doc = self._data.get(container, {}).get(doc_id)
        if doc is None or not self._alive(doc):
            return None
        return {k: v for k, v in copy.deepcopy(doc).items() if k != "_created"}

    def create(self, container, doc):
        bucket = self._data.setdefault(container, {})
        existing = bucket.get(doc["id"])
        if existing is not None and self._alive(existing):
            raise ConflictError(doc["id"])
        stored = copy.deepcopy(doc)
        stored["_created"] = self._clock()
        bucket[doc["id"]] = stored

    def replace(self, container, doc):
        bucket = self._data.setdefault(container, {})
        old = bucket.get(doc["id"])
        stored = copy.deepcopy(doc)
        stored["_created"] = old["_created"] if old else self._clock()
        bucket[doc["id"]] = stored

    def delete(self, container, doc_id):
        self._data.get(container, {}).pop(doc_id, None)


class CosmosStore:
    def __init__(self, uri, key, database):
        from azure.cosmos import CosmosClient

        self._client = CosmosClient(uri, credential=key)
        self._db = self._client.get_database_client(database)
        self._containers = {}

    def _c(self, name):
        if name not in self._containers:
            self._containers[name] = self._db.get_container_client(name)
        return self._containers[name]

    def check_ttl_enabled(self, name):
        """Cadastros pendentes dependem do TTL do container para expirar."""
        try:
            props = self._c(name).read()
            if props.get("defaultTtl") is None:
                log_event(
                    "Container sem TTL ativo: cadastros pendentes não vão expirar",
                    level=30, container=name,
                )
        except Exception as exc:  # não impede a API de subir
            log_event("Não foi possível checar o TTL", level=30, container=name, error=type(exc).__name__)

    def get(self, container, doc_id):
        from azure.cosmos import exceptions

        try:
            return self._c(container).read_item(item=doc_id, partition_key=doc_id)
        except exceptions.CosmosResourceNotFoundError:
            return None
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc

    def create(self, container, doc):
        from azure.cosmos import exceptions

        try:
            self._c(container).create_item(body=doc)
        except exceptions.CosmosResourceExistsError as exc:
            raise ConflictError(doc["id"]) from exc
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc

    def replace(self, container, doc):
        try:
            self._c(container).replace_item(item=doc["id"], body=doc)
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc

    def delete(self, container, doc_id):
        from azure.cosmos import exceptions

        try:
            self._c(container).delete_item(item=doc_id, partition_key=doc_id)
        except exceptions.CosmosResourceNotFoundError:
            pass
        except Exception as exc:
            raise StoreError(type(exc).__name__) from exc
