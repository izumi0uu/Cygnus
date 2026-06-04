from __future__ import annotations

import unittest

from cygnus.domain import AudienceContext, AudienceFilter, Visibility


class AudienceFilterTests(unittest.TestCase):
    def test_global_filter_is_valid_with_visibility_only(self) -> None:
        audience = AudienceFilter(visibility=Visibility.EXTERNAL)

        self.assertTrue(audience.is_global)
        self.assertEqual(
            audience.to_dict(),
            {
                "visibility": "external",
                "brands": [],
                "product_lines": [],
                "plans": [],
                "regions": [],
                "languages": [],
                "product_versions": [],
                "is_global": True,
            },
        )

    def test_blank_dimension_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AudienceFilter(visibility=Visibility.INTERNAL, brands=("acme", " "))

    def test_filter_matches_specific_context(self) -> None:
        audience = AudienceFilter(
            visibility=Visibility.EXTERNAL,
            product_lines=("billing",),
            plans=("enterprise",),
            regions=("eu",),
        )
        matching = AudienceContext(
            visibility=Visibility.EXTERNAL,
            product_line="billing",
            plan="enterprise",
            region="eu",
        )
        non_matching = AudienceContext(
            visibility=Visibility.EXTERNAL,
            product_line="billing",
            plan="free",
            region="eu",
        )

        self.assertTrue(audience.matches(matching))
        self.assertFalse(audience.matches(non_matching))

    def test_context_rejects_blank_values(self) -> None:
        with self.assertRaises(ValueError):
            AudienceContext(visibility=Visibility.EXTERNAL, language=" ")


if __name__ == "__main__":
    unittest.main()
