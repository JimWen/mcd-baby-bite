"""到店自提 / 得来速 / 麦乐送 三种场景的参数规则（见 docs/design.md 3.1）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Scene:
    key: str
    label: str
    be_type: int
    order_type: int
    needs_be_code: bool
    needs_take_way: bool
    needs_address: bool


SCENES = {
    "pickup": Scene("pickup", "到店自提", 1, 1, False, True, False),
    "drive": Scene("drive", "得来速", 5, 1, True, True, False),
    "delivery": Scene("delivery", "麦乐送", 2, 2, True, False, True),
}


def get_scene(key: str) -> Scene:
    try:
        return SCENES[key]
    except KeyError:
        raise ValueError(f"未知场景：{key}，可选：{'、'.join(SCENES)}") from None


def store_args(scene: Scene, store_code: str, be_code: Optional[str] = None,
               reservation_date: Optional[str] = None) -> dict:
    """生成 query-meals / query-meal-detail / calculate-price / create-order 共用的门店参数。"""
    if not store_code:
        raise ValueError("门店编码不能为空")
    if scene.needs_be_code and not be_code:
        raise ValueError(f"{scene.label}场景必须提供 beCode")
    args = {"storeCode": store_code, "orderType": scene.order_type, "beType": scene.be_type}
    if scene.needs_be_code:
        args["beCode"] = be_code
    if reservation_date:
        args["reservationDate"] = reservation_date
    return args
