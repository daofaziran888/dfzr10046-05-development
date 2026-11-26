"""业务路由汇总：字段裁决专用路由先行注册，其余模块共用一套资源路由。"""
from __future__ import annotations

from app.routers import resource, ruling

ROUTERS = [ruling, resource]
