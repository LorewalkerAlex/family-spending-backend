"""Canonical YAML persistence for reviewed Mapping knowledge."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.mapping import UNCLASSIFIED_CATEGORY, MappingCatalog
from family_spending_backend.persistence.filesystem.atomic import atomic_write_text
from family_spending_backend.persistence.filesystem.layout import FilesystemLayout


class MappingStoreError(RuntimeError):
    """Reviewed Mapping state is malformed or cannot be persisted."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader, node: MappingNode, deep: bool = False
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found unhashable key {key!r}",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _read_yaml_mapping(path: Path) -> dict[object, object]:
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise MappingStoreError(f"Unable to read Mapping state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MappingStoreError(f"Expected YAML mapping in {path}, got {type(value).__name__}")
    return value


def _exact_text(value: object, *, label: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise MappingStoreError(
            f"Invalid {label} in {path}: expected normalized non-empty text, got {value!r}"
        )
    return value


def _decode_catalog(merchants_path: Path, categories_path: Path) -> MappingCatalog:
    raw_merchants = _read_yaml_mapping(merchants_path)
    raw_categories = _read_yaml_mapping(categories_path)
    description_to_merchant: dict[str, str] = {}
    merchant_names: set[str] = set()
    for raw_merchant, raw_descriptions in raw_merchants.items():
        merchant = _exact_text(raw_merchant, label="merchant", path=merchants_path)
        if not isinstance(raw_descriptions, list) or not raw_descriptions:
            raise MappingStoreError(f"Merchant {merchant!r} must have a non-empty description list")
        merchant_names.add(merchant)
        for raw_description in raw_descriptions:
            description = _exact_text(raw_description, label="description", path=merchants_path)
            previous = description_to_merchant.get(description)
            if previous is not None:
                raise MappingStoreError(
                    f"Description {description!r} is assigned to both {previous!r} and {merchant!r}"
                )
            description_to_merchant[description] = merchant

    merchant_to_category: dict[str, str] = {}
    categories: set[str] = set()
    for raw_category, raw_merchants in raw_categories.items():
        category = _exact_text(raw_category, label="category", path=categories_path)
        if category == UNCLASSIFIED_CATEGORY:
            raise MappingStoreError(f"Runtime category {category!r} must not be persisted")
        if not isinstance(raw_merchants, list) or not raw_merchants:
            raise MappingStoreError(f"Category {category!r} must have a non-empty merchant list")
        categories.add(category)
        for raw_merchant in raw_merchants:
            merchant = _exact_text(raw_merchant, label="merchant", path=categories_path)
            previous = merchant_to_category.get(merchant)
            if previous is not None:
                raise MappingStoreError(
                    f"Merchant {merchant!r} is assigned to both {previous!r} and {category!r}"
                )
            merchant_to_category[merchant] = category

    if merchant_names != set(merchant_to_category):
        missing = sorted(merchant_names - set(merchant_to_category))
        unknown = sorted(set(merchant_to_category) - merchant_names)
        raise MappingStoreError(
            "Mapping merchant sets differ; "
            f"missing_categories={missing!r}, unknown_merchants={unknown!r}"
        )
    try:
        return MappingCatalog(description_to_merchant, merchant_to_category, frozenset(categories))
    except DomainInvariantError as exc:
        raise MappingStoreError(f"Invalid Mapping state: {exc}") from exc


@dataclass(frozen=True, slots=True)
class FilesystemMappingStore:
    layout: FilesystemLayout

    def load(self) -> MappingCatalog:
        merchants_exists = self.layout.merchant_mappings.exists()
        categories_exists = self.layout.category_mappings.exists()
        if not merchants_exists and not categories_exists:
            return MappingCatalog.empty()
        if merchants_exists != categories_exists:
            raise MappingStoreError(
                "Canonical Mapping state is incomplete: "
                "merchants.yaml and categories.yaml must exist together"
            )
        return _decode_catalog(self.layout.merchant_mappings, self.layout.category_mappings)

    def replace(self, mappings: MappingCatalog) -> None:
        if not mappings.description_to_merchant:
            self.layout.merchant_mappings.unlink(missing_ok=True)
            self.layout.category_mappings.unlink(missing_ok=True)
            return
        descriptions: defaultdict[str, list[str]] = defaultdict(list)
        for description, merchant in mappings.description_to_merchant.items():
            descriptions[merchant].append(description)
        merchants_payload = {
            merchant: sorted(descriptions[merchant]) for merchant in sorted(descriptions)
        }
        merchants: defaultdict[str, list[str]] = defaultdict(list)
        for merchant, category in mappings.merchant_to_category.items():
            merchants[category].append(merchant)
        categories_payload = {
            category: sorted(merchants[category]) for category in sorted(merchants)
        }
        try:
            atomic_write_text(
                self.layout.merchant_mappings,
                yaml.safe_dump(merchants_payload, allow_unicode=True, sort_keys=False),
            )
            atomic_write_text(
                self.layout.category_mappings,
                yaml.safe_dump(categories_payload, allow_unicode=True, sort_keys=False),
            )
        except OSError as exc:
            raise MappingStoreError(f"Unable to persist Mapping state: {exc}") from exc
