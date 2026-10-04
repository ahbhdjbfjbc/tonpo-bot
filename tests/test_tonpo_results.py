from types import SimpleNamespace

from gateway_client.adapter import _execution_result


def test_tonpo_result_requires_a_ticket_before_accepting_order():
    assert _execution_result(SimpleNamespace(success=True, ticket=712)) == {
        'success': True, 'status': 'accepted', 'orderId': '712'
    }
    missing = _execution_result(SimpleNamespace(success=True, ticket=0))
    assert missing['success'] is False
    assert missing['status'] == 'unknown'
    rejected = _execution_result(SimpleNamespace(success=False, ticket=0))
    assert rejected['success'] is False
    assert rejected['status'] == 'rejected'
