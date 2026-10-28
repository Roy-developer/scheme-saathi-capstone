import json
from importlib import resources
from pathlib import Path

from src.ui.models import DevelopmentScenario, FixtureSet


class FixtureDataProvider:
    def __init__(self, fixture_path: Path | None = None) -> None:
        if fixture_path is None:
            fixture_text = (
                resources.files("src.ui")
                .joinpath("fixtures", "ignwps_mh.json")
                .read_text(encoding="utf-8")
            )
        else:
            fixture_text = fixture_path.read_text(encoding="utf-8")

        payload = json.loads(fixture_text)
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
