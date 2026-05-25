from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Tuple


MetricKey = Tuple[str, Tuple[Tuple[str, str], ...]]


@dataclass
class MetricSample:
    name: str
    value: Decimal
    labels: Dict[str, str]


class MetricsRegistry:
    def __init__(self) -> None:
        self._values: Dict[MetricKey, Decimal] = {}

    def inc(self, name: str, amount: object = 1, **labels: str) -> None:
        key = self._key(name, labels)
        self._values[key] = self._values.get(key, Decimal("0")) + Decimal(str(amount))

    def set(self, name: str, value: object, **labels: str) -> None:
        self._values[self._key(name, labels)] = Decimal(str(value))

    def get(self, name: str, **labels: str) -> Decimal:
        return self._values.get(self._key(name, labels), Decimal("0"))

    def samples(self) -> Dict[MetricKey, Decimal]:
        return dict(self._values)

    def prometheus_text(self) -> str:
        lines = []
        for (name, label_items), value in sorted(self._values.items()):
            if label_items:
                label_text = ",".join('{0}="{1}"'.format(k, v) for k, v in label_items)
                lines.append("{0}{{{1}}} {2}".format(name, label_text, value))
            else:
                lines.append("{0} {1}".format(name, value))
        return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def _key(name: str, labels: Dict[str, str]) -> MetricKey:
        return name, tuple(sorted((str(k), str(v)) for k, v in labels.items()))

