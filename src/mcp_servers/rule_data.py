"""Share validated rule and fact bundle state across MCP service startup."""

from functools import lru_cache

from src.config import PROJECT_ROOT, test_rule_package_directory, test_scheme_data_directory
from src.rules.data_provider import RulePackageProvider


@lru_cache(maxsize=1)
def get_active_rule_data() -> RulePackageProvider:
    """Load every required bundle once, failing service startup on bad data."""

    package_directory = test_rule_package_directory()
    provider = (
        RulePackageProvider()
        if package_directory is None
        else RulePackageProvider(package_directory, allow_development=True)
    )
    from src.documents.checklists import load_checklist_snapshot
    from src.documents.forms import load_mock_form_snapshot

    scheme_directory = test_scheme_data_directory() or PROJECT_ROOT / "data" / "schemes"
    for scheme_id, bundle in provider.bundles.items():
        checklist_directory = scheme_directory / "document_checklists"
        if (checklist_directory / f"{scheme_id}.json").exists():
            snapshot = load_checklist_snapshot(
                scheme_id, registry=provider.registry, bundle=bundle,
                checklist_directory=checklist_directory,
                evidence_file=scheme_directory / "document_evidence.json",
            )
            if snapshot.checklist is None:
                raise ValueError("Configured checklist is incompatible with its scheme bundle.")
        form_directory = scheme_directory / "mock_forms"
        if (form_directory / f"{scheme_id}.json").exists():
            form = load_mock_form_snapshot(
                scheme_id, provider.registry, bundle=bundle,
                form_directory=form_directory,
            )
            if form.mapping is None:
                raise ValueError("Configured mock form is incompatible with its scheme bundle.")
    return provider
