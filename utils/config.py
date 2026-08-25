from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and earlier
    import tomli as tomllib


@dataclass(frozen=True)
class UniverseConfig:
    symbols: list[str]
    names: dict[str, str]
    index_symbols: list[str]
    max_symbols: int
    mode: str
    board_top_n: int


@dataclass(frozen=True)
class DataConfig:
    start_date: str
    end_date: str
    adjust: str
    cache_dir: Path
    provider: str
    workers: int


@dataclass(frozen=True)
class StrategyConfig:
    rebalance: str
    top_n: int
    min_history_days: int


@dataclass(frozen=True)
class OutputConfig:
    report_dir: Path


@dataclass(frozen=True)
class AppConfig:
    universe: UniverseConfig
    data: DataConfig
    strategy: StrategyConfig
    factors: dict[str, float]
    output: OutputConfig


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open("rb") as file:
        raw = tomllib.load(file)

    base_dir = config_path.parent.parent
    data_raw = raw["data"]
    output_raw = raw["output"]

    universe_raw = raw["universe"]
    symbols = [str(item).zfill(6) for item in universe_raw.get("symbols", [])]
    names = {str(symbol).zfill(6): str(name) for symbol, name in raw["universe"].get("names", {}).items()}
    index_symbols = [str(item).zfill(6) for item in universe_raw.get("index_symbols", [])]

    return AppConfig(
        universe=UniverseConfig(
            symbols=symbols,
            names=names,
            index_symbols=index_symbols,
            max_symbols=int(universe_raw.get("max_symbols", 0)),
            mode=str(universe_raw.get("mode", "index")),
            board_top_n=int(universe_raw.get("board_top_n", 10)),
        ),
        data=DataConfig(
            start_date=str(data_raw["start_date"]),
            end_date=str(data_raw.get("end_date", "")),
            adjust=str(data_raw.get("adjust", "qfq")),
            cache_dir=(base_dir / data_raw.get("cache_dir", "data/raw")).resolve(),
            provider=str(data_raw.get("provider", "auto")),
            workers=int(data_raw.get("workers", 8)),
        ),
        strategy=StrategyConfig(
            rebalance=str(raw["strategy"].get("rebalance", "W-FRI")),
            top_n=int(raw["strategy"].get("top_n", 10)),
            min_history_days=int(raw["strategy"].get("min_history_days", 80)),
        ),
        factors={name: float(weight) for name, weight in raw["factors"].items()},
        output=OutputConfig(report_dir=(base_dir / output_raw.get("report_dir", "reports")).resolve()),
    )
