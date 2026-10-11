import unittest

from babybite.errors import McdBusinessError
from babybite.scenes import get_scene, store_args


class SceneTest(unittest.TestCase):
    def test_pickup_never_sends_be_code(self):
        args = store_args(get_scene("pickup"), "1450713", be_code="X", reservation_date="2026-10-12 11:30")
        self.assertEqual(args, {"storeCode": "1450713", "orderType": 1, "beType": 1,
                                "reservationDate": "2026-10-12 11:30"})

    def test_drive_requires_be_code(self):
        with self.assertRaises(ValueError):
            store_args(get_scene("drive"), "1450713")
        self.assertEqual(store_args(get_scene("drive"), "S1", be_code="B1"),
                         {"storeCode": "S1", "orderType": 1, "beType": 5, "beCode": "B1"})

    def test_delivery_uses_order_type_2(self):
        scene = get_scene("delivery")
        self.assertEqual((scene.be_type, scene.order_type, scene.needs_address, scene.needs_take_way), (2, 2, True, False))

    def test_unknown_scene_and_empty_store(self):
        with self.assertRaises(ValueError):
            get_scene("teleport")
        with self.assertRaises(ValueError):
            store_args(get_scene("pickup"), "")

    def test_business_error_keeps_code(self):
        err = McdBusinessError(600057, "门店可能已关闭")
        self.assertEqual(err.code, 600057)
        self.assertIn("600057", str(err))


if __name__ == "__main__":
    unittest.main()
