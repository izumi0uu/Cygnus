from __future__ import annotations

import unittest

from cygnus.review import ReviewItemQuery, get_review_item_detail


class ReviewDetailTests(unittest.TestCase):
    def test_get_review_item_detail_returns_cyg7_shape(self) -> None:
        payload = get_review_item_detail(ReviewItemQuery(object_ref='cp-source-1')).to_dict()
        self.assertEqual(payload['detail_id'], 'detail:cp-source-1')
        self.assertIn('risk_frame', payload)
        self.assertIn('evidence_strength', payload)
        self.assertIn('audience_impact', payload)
        self.assertEqual(payload['risk_frame']['risk_type'], 'source_blindness')

    def test_get_review_item_detail_raises_when_item_missing(self) -> None:
        with self.assertRaises(ValueError):
            get_review_item_detail(ReviewItemQuery(object_ref='missing-ref'))
