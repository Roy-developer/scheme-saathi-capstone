"""Load and query the validated synthetic policy fixture pack."""

import json
from importlib import resources
from pathlib import Path

from src.ui.models import DevelopmentScenario, FixtureSet


class FixtureDataProvider:
    """Provide typed access to packaged or explicitly supplied fixture data."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        """Load JSON fixtures and reject data that violates the model contract."""

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
        """Return the fully validated fixture set."""

        return self._fixtures

    def visible_scenarios(self) -> list[DevelopmentScenario]:
        """Return only scenarios intentionally exposed in the demonstration UI."""

        return [
            scenario
            for scenario in self._fixtures.scenarios
            if scenario.visible_in_ui
        ]

    def get_scenario(self, scenario_id: str) -> DevelopmentScenario:
        """Find a scenario by ID or fail clearly when the ID is unknown."""

        for scenario in self._fixtures.scenarios:
            if scenario.scenario_id == scenario_id:
                return scenario
        raise KeyError(f"Unknown development scenario: {scenario_id}")
