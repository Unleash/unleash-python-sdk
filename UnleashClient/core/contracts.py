from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Optional


class UnleashClientContract(ABC):
    """This is the public contract for Unleash clients. All implementers must adhere to this interface. While children
    may expose other methods, these are the methods that a caller can always expect to be present.
    """

    @abstractmethod
    def is_enabled(
        self,
        feature_name: str,
        context: Optional[dict] = None,
        fallback_function: Callable = None,
    ) -> bool:

        pass

    @abstractmethod
    def get_variant(self, feature_name: str, context: Optional[dict] = None) -> dict:
        pass

    @abstractmethod
    def feature_definitions(self) -> dict:
        pass
