from abc import ABC, abstractmethod
from execution.errors import ExecutionBlockedError
from execution.config import EXECUTION_ENABLED


class BaseExecutor(ABC):

    def _check_enabled(self):
        if not EXECUTION_ENABLED:
            raise ExecutionBlockedError(
                "Execution is disabled by design"
            )

    @abstractmethod
    def place_order(self, *args, **kwargs):
        pass
