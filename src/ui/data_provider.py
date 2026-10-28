import json
from pathlib import Path

from src.ui.models import DevelopmentScenario, FixtureSet


class FixtureDataProvider:
    def __init__(self, fixture_path: Path | None = None) -> None:
        path = fixture_path or (
            Path(__file__).parent / "fixtures" / "ignwps_mh.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._fixtures = FixtureSet.model_validate(payload)

    @property
    def fixtures(self) -> FixtureSet:
        return self._fixtures

    def visible_scenarios(self) -> list[DevelopmentScenario]:
        return [
            scenario
            for scenario in self._fixtures.scenarios
            if scenario.visible_in_ui
        ]

    def get_scenario(self, scenario_id: str) -> DevelopmentScenario:
        for scenario in self._fixtures.scenarios:
            if scenario.scenario_id == scenario_id:
                return scenario
        raise KeyError(f"Unknown development scenario: {scenario_id}")
