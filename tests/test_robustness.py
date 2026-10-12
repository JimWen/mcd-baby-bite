"""批次 K 最终审查的行为回归；所有写操作仅使用本地假客户端。"""
import http.client
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from babybite.age_rules import sodium_budget
from babybite.cards import plan_to_dict, render_html, render_markdown
from babybite.cli import EXIT_ERROR, main
from babybite.customize import CustomizedItem, CustomizedLine
from babybite.errors import TransportError
from babybite.mcp_client import McdClient
from babybite.phone_cards import AgeRow, render_age_card
from babybite.planner import build_plans, plan_for_item
from babybite.scenes import get_scene
from babybite.share import build_note
from tests.helpers import load_detail, load_index, load_menu
from tests.test_cards import make_result
from tests.test_cli import ScriptedClient


class UnknownNutritionTest(unittest.TestCase):
    def result_with_unknown(self, unknown_side=False):
        main_line = CustomizedLine('1', '主食', 'X', '汉堡包' if unknown_side else '神秘新品堡', 1, (), (), None)
        side = CustomizedLine('2', '饮料', 'Y', '神秘牛奶' if unknown_side else '纯牛奶', 1, (), (), None)
        item = CustomizedItem('X', '神秘开心乐园餐', 1, (main_line, side), ())
        result = make_result(age=30)
        result.plans = [plan_for_item(item, load_index(), sodium_budget(30))]
        return result

    def test_unknown_main_or_side_never_becomes_confirmed_recommendation(self):
        candidates = [m for m in load_menu() if m.code == '9900016057']
        detail = load_detail('9900016057')
        for unknown_side in (False, True):
            with self.subTest(unknown_side=unknown_side):
                result = self.result_with_unknown(unknown_side)
                with patch('babybite.planner.customize_meal', return_value=result.plans[0].item):
                    plans, excluded = build_plans(candidates, {candidates[0].code: detail}, load_index(),
                                                  sodium_budget(30), 30)
                self.assertEqual(plans, [])
                self.assertIn('无官方营养数据', excluded[0][1])

    def test_unknown_outputs_distinguish_subtotal_from_total(self):
        result = self.result_with_unknown()
        for render in (render_markdown, render_html):
            text = render(result)
            self.assertIn('已知项钠小计', text)
            self.assertIn('总量无法确认', text)
            self.assertNotIn('本餐宝宝钠合计', text)
        top = plan_to_dict(result)['plans'][0]
        self.assertIsNone(top['kidSodiumMg'])
        self.assertIsNone(top['mealBudgetPct'])
        self.assertIsNone(top['dayLimitPct'])
        self.assertEqual(top['knownSodiumSubtotalMg'], 73.0)
        self.assertNotIn('建议先给 1/2', result.plans[0].components[0].note)

    def test_legacy_share_and_age_card_do_not_promise_unknown_total(self):
        result = self.result_with_unknown()
        saved = plan_to_dict(result)
        # Older plan files contain a number even when unknownNutrition is populated.
        saved['plans'][0]['kidSodiumMg'] = 73
        note = build_note(saved)['content']
        self.assertIn('总量无法确认', note)
        self.assertNotIn('不超过', note)
        card = render_age_card([AgeRow(30, '2-3 岁', 2, 262, result.plans[0])], '测试店', None)
        self.assertIn('总量无法确认', card)
        self.assertNotIn('≤73mg', card)


class InterruptedResponseTest(unittest.TestCase):
    def client(self, failures):
        events = []
        responses = []
        token = 'test-private-value'

        class Response(io.BytesIO):
            headers = {'Content-Type': 'application/json'}

            def read(self, *args):
                if len(events) <= failures:
                    raise http.client.IncompleteRead(token.encode(), 20)
                return super().read(*args)

        def opener(request, timeout):
            events.append(json.loads(request.data)['params']['name'])
            body = {'result': {'structuredContent': {'success': True, 'code': 200, 'data': 'ok'}}}
            response = Response(json.dumps(body).encode())
            responses.append(response)
            return response

        client = McdClient(token, opener=opener, sleep=lambda _: None)
        client._initialized = True
        return client, events, responses, token

    def test_read_response_interruption_retries_and_closes(self):
        client, events, responses, _ = self.client(1)
        self.assertEqual(client.call_tool('query-meals', {})['data'], 'ok')
        self.assertEqual(events, ['query-meals', 'query-meals'])
        self.assertTrue(all(r.closed for r in responses))

    def test_read_exhaustion_is_transport_error(self):
        client, events, responses, token = self.client(10)
        with self.assertRaises(TransportError) as ctx:
            client.call_tool('query-meals', {})
        self.assertEqual(len(events), 3)
        self.assertTrue(all(r.closed for r in responses))
        self.assertNotIn(token, str(ctx.exception))

    def test_write_response_interruption_is_never_retried(self):
        client, events, responses, token = self.client(10)
        with self.assertRaises(TransportError) as ctx:
            client.call_tool('create-order', {})
        self.assertEqual(events, ['create-order'])
        self.assertTrue(all(r.closed for r in responses))
        self.assertNotIn(token, str(ctx.exception))
        self.assertIn('核对', str(ctx.exception))


class MissingPriceTest(unittest.TestCase):
    def test_invalid_price_blocks_order_for_pickup_and_delivery(self):
        result = make_result()
        result.offline = False
        for scene in ('pickup', 'delivery'):
            for price in (None, '2350', False, -1, float('nan'), float('inf'), 2.5):
                with self.subTest(scene=scene, price=price), tempfile.TemporaryDirectory() as tmp:
                    result.scene = get_scene(scene)
                    saved = plan_to_dict(result)
                    saved['store']['beCode'] = 'test-be-code'
                    saved['addressId'] = 'test-address-id'
                    path = Path(tmp) / 'plan.json'
                    path.write_text(json.dumps(saved), encoding='utf-8')
                    price_data = {'takeWayList': [{'code': 'counter'}]}
                    if price is not None:
                        price_data['price'] = price
                    client = ScriptedClient({'calculate-price': {'data': price_data},
                                             'create-order': {'data': {'orderId': 'test-order'}}})
                    with redirect_stderr(io.StringIO()):
                        code = main(['order', '--plan', str(path), '--confirm'],
                                    client_factory=lambda _: client, out=io.StringIO())
                    self.assertEqual(code, EXIT_ERROR)
                    self.assertEqual([name for name, _ in client.calls], ['calculate-price'])


if __name__ == '__main__':
    unittest.main()
