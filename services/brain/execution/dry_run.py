from execution.base import BaseExecutor


class DryRunExecutor(BaseExecutor):

    def place_order(self, order: dict):
        # ❌ no execution
        return {
            "status": "DRY_RUN",
            "order": order,
            "message": "Order simulated, not executed"
        }
