import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).parents[1] / "src" / "family_spending_backend" / "domain"
APPLICATION_ROOT = Path(__file__).parents[1] / "src" / "family_spending_backend" / "application"
HTTP_ROOT = Path(__file__).parents[1] / "src" / "family_spending_backend" / "interfaces" / "http"
FORBIDDEN_DOMAIN_IMPORTS = {
    "fastapi",
    "json",
    "pathlib",
    "pydantic",
    "pydantic_settings",
    "starlette",
    "yaml",
}


def imported_modules(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_domain_has_no_framework_persistence_or_outer_layer_dependencies() -> None:
    violations: list[str] = []

    for source_file in DOMAIN_ROOT.glob("*.py"):
        for module in imported_modules(source_file):
            root_module = module.split(".", maxsplit=1)[0]
            if root_module in FORBIDDEN_DOMAIN_IMPORTS:
                violations.append(f"{source_file.name}: forbidden import {module}")
            if module.startswith("family_spending_backend.") and not module.startswith(
                "family_spending_backend.domain"
            ):
                violations.append(f"{source_file.name}: outer-layer import {module}")

    assert not violations, "\n".join(violations)


def test_application_depends_only_on_application_and_domain_packages() -> None:
    violations: list[str] = []
    allowed_prefixes = (
        "family_spending_backend.application",
        "family_spending_backend.domain",
    )

    for source_file in APPLICATION_ROOT.rglob("*.py"):
        for module in imported_modules(source_file):
            if module.startswith("family_spending_backend.") and not module.startswith(
                allowed_prefixes
            ):
                violations.append(f"{source_file.name}: outer-layer import {module}")

    assert not violations, "\n".join(violations)


def test_http_uses_one_typed_container_instead_of_dynamic_app_state_services() -> None:
    violations: list[str] = []
    for source_file in HTTP_ROOT.rglob("*.py"):
        source = source_file.read_text(encoding="utf-8")
        for line_number, line in enumerate(source.splitlines(), start=1):
            if "app.state." in line and source_file.name not in {"app.py", "dependencies.py"}:
                violations.append(f"{source_file.name}:{line_number}: {line.strip()}")
    assert not violations, "\n".join(violations)


def test_removed_broad_financial_state_does_not_return() -> None:
    root = Path(__file__).parents[1] / "src" / "family_spending_backend"
    violations = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if "FinancialState" in path.read_text(encoding="utf-8")
    ]
    assert not violations, violations
