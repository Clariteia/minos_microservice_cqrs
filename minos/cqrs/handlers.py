"""
Copyright (C) 2021 Clariteia SL

This file is part of minos framework.

Minos framework can not be copied and/or distributed without the express permission of Clariteia SL.
"""
from uuid import (
    UUID,
)

from minos.common import (
    AggregateDiff,
    DataTransferObject,
    MinosSagaManager,
    ModelRefExtractor,
    ModelRefInjector,
    ModelType,
)
from minos.saga import (
    Saga,
    SagaContext,
    SagaExecution,
    SagaStatus,
)

from .exceptions import (
    MinosQueryServiceException,
)


class PreEventHandler:
    """Pre Event Handler class."""

    @classmethod
    async def handle(cls, diff: AggregateDiff, saga_manager: MinosSagaManager) -> AggregateDiff:
        """Handle pre event function.

        :param diff: The initial aggregate difference.
        :param saga_manager: The saga manager to be used to compute the queries to another microservices.
        :return: The recomposed aggregate difference.
        """
        definition = cls.build_saga(diff)
        execution = await saga_manager.run(
            definition=definition, pause_on_disk=False, return_execution=True, raise_on_error=True
        )
        if not isinstance(execution, SagaExecution) or execution.status != SagaStatus.Finished:
            raise MinosQueryServiceException("The saga execution could not finish.")
        return execution.context["diff"]

    @classmethod
    def build_saga(cls, diff: AggregateDiff) -> Saga:
        """Build a saga to query the referenced aggregates.

        :param diff: The base aggregate difference.
        :return: A saga instance.
        """
        missing = ModelRefExtractor(diff.fields_diff).build()

        saga = Saga("")
        for name, uuids in missing.items():
            saga = (
                saga.step()
                .invoke_participant(f"Get{name}s", cls.invoke_callback, SagaContext(uuids=list(uuids)))
                .on_reply(f"{name}s")
            )
        saga = saga.commit(cls.commit_callback, parameters=SagaContext(diff=diff))

        return saga

    # noinspection PyUnusedLocal
    @staticmethod
    def invoke_callback(context: SagaContext, uuids: list[UUID]) -> DataTransferObject:
        """Callback to prepare data before invoking participants.

        :param context: The saga context (ignored).
        :param uuids: The list of identifiers.
        :return: A dto instance.
        """
        return ModelType.build("Query", {"uuids": list[UUID]})(uuids=uuids)

    @classmethod
    def commit_callback(cls, context: SagaContext, diff: AggregateDiff) -> SagaContext:
        """Callback to be executed at the end of the saga.

        :param context: The saga execution context.
        :param diff: The initial aggregate difference.
        :return: A saga context containing the enriched aggregate difference.
        """

        recovered = dict()
        for k in context.keys():
            for v in context[k]:
                recovered[v.uuid] = v

        diff = ModelRefInjector(diff, recovered).build()
        return SagaContext(diff=diff)
