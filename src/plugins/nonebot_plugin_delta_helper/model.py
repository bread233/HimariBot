from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import text
from src.service.nonebot_plugin_orm import Model

class UserData(Model):
    __tablename__ = "user_data"

    qq_id: Mapped[int] = mapped_column(primary_key=True, comment="用户QQ号")
    group_id: Mapped[int] = mapped_column(comment="群号")
    access_token: Mapped[str] = mapped_column(comment="访问令牌")
    openid: Mapped[str] = mapped_column(comment="OpenID")
    if_remind_safehouse: Mapped[bool] = mapped_column(default=False, server_default=text('false'), comment="是否提醒特勤处生产完成")
    platform: Mapped[str] = mapped_column(default='qq', server_default=text('qq'), comment="平台类型")
    if_broadcast_record: Mapped[bool] = mapped_column(default=True, server_default=text('true'), comment="是否广播最新战绩")

class LatestRecord(Model):
    __tablename__ = "latest_record"

    qq_id: Mapped[int] = mapped_column(primary_key=True, comment="用户QQ号")
    latest_record_id: Mapped[str] = mapped_column(comment="最新战绩ID")
    latest_tdm_record_id: Mapped[str] = mapped_column(default='temp', server_default=text('temp'), comment="最新TDM战绩ID")

class SafehouseRecord(Model):
    __tablename__ = "safehouse_record"

    qq_id: Mapped[int] = mapped_column(primary_key=True, comment="用户QQ号")
    device_id: Mapped[str] = mapped_column(primary_key=True, comment="设备ID")
    object_id: Mapped[int] = mapped_column(comment="生产物品ID")
    object_name: Mapped[str] = mapped_column(comment="生产物品名称")
    place_name: Mapped[str] = mapped_column(comment="工作台名称")
    left_time: Mapped[int] = mapped_column(comment="剩余时间（秒）")
    push_time: Mapped[int] = mapped_column(comment="推送时间戳")
