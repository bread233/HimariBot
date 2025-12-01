from abc import abstractmethod
from typing import Union, Tuple, Optional, Literal

from nonebot.adapters import Bot, Event
from nonebot.permission import Permission
from ..nonebot_plugin_uninfo import get_session

_IdType = Union[str, int]
BYPASS_ENTITY = "__bypass"


class CooldownEntity:
    """
    **限制实体类**
    """

    __slots__ = ()

    @abstractmethod
    def __init__(self) -> None: ...

    @abstractmethod
    async def get_entity_id(self, bot: Bot, event: Event) -> str:
        """
        返回被限制实体的唯一标识符，统一为 str
        """
        ...


class GlobalScope(CooldownEntity):
    """
    **全局限制实体**
    """

    def __init__(self) -> None:
        pass

    async def get_entity_id(self, bot: Bot, event: Event) -> str:
        return "__global"


class UserScope(CooldownEntity):
    """
    **用户限制实体**
    """

    def __init__(
        self,
        *,
        whitelist: Optional[Tuple[_IdType, ...]] = None,
        permission: Optional[Permission] = None
    ) -> None:
        if whitelist is not None:
            self.whitelist = tuple(str(x) for x in whitelist)
        else:
            self.whitelist = None
        self.permission = permission

    async def get_entity_id(self, bot: Bot, event: Event) -> str:
        sess = await get_session(bot, event)
        if sess is None:
            return BYPASS_ENTITY

        user_id = sess.user.id
        if self.whitelist is not None and user_id in self.whitelist:
            return BYPASS_ENTITY
        if self.permission is not None and (await self.permission(bot, event)):
            return BYPASS_ENTITY
        return f"u`{user_id}`"


class SceneScope(CooldownEntity):
    """
    **场景限制实体**
    """

    def __init__(
        self,
        *,
        whitelist: Optional[Tuple[_IdType, ...]] = None,
        permission: Optional[Permission] = None
    ) -> None:
        if whitelist is not None:
            self.whitelist = tuple(str(x) for x in whitelist)
        else:
            self.whitelist = None
        self.permission = permission

    async def get_entity_id(self, bot: Bot, event: Event) -> str:
        sess = await get_session(bot, event)
        if sess is None:
            return BYPASS_ENTITY

        scene_id = sess.scene.id
        if self.whitelist is not None and scene_id in self.whitelist:
            return BYPASS_ENTITY
        if self.permission is not None and (await self.permission(bot, event)):
            return BYPASS_ENTITY
        return f"s`{scene_id}`"


class UserSceneScope(CooldownEntity):
    """
    **用户场景限制实体**
    """

    def __init__(
        self,
        *,
        whitelist: Optional[Tuple[Tuple[Union[_IdType, Literal["*"]], Union[_IdType, Literal["*"]]], ...]] = None,
        permission: Optional[Permission] = None,
    ) -> None:
        if whitelist is not None:
            self.whitelist = tuple((str(x[0]), str(x[1])) for x in whitelist)
        else:
            self.whitelist = None
        self.permission = permission

    async def get_entity_id(self, bot: Bot, event: Event) -> str:
        sess = await get_session(bot, event)
        if sess is None:
            return BYPASS_ENTITY

        user_id = sess.user.id
        scene_id = sess.scene.id
        if self.whitelist is not None:
            for uid, sid in self.whitelist:
                if (uid == "*" or uid == user_id) and (sid == "*" or sid == scene_id):
                    return BYPASS_ENTITY
        if self.permission is not None and (await self.permission(bot, event)):
            return BYPASS_ENTITY
        return f"u`{user_id}`_s`{scene_id}`"


class PrivateScope(CooldownEntity):
    def __init__(
        self,
        *,
        whitelist: Optional[Tuple[_IdType, ...]] = None,
        permission: Optional[Permission] = None
    ) -> None:
        if whitelist is not None:
            self.whitelist = tuple(str(x) for x in whitelist)
        else:
            self.whitelist = None
        self.permission = permission

    async def get_entity_id(self, bot: Bot, event: Event) -> str:
        sess = await get_session(bot, event)
        if sess is None or not sess.scene.is_private:
            return BYPASS_ENTITY

        user_id = sess.user.id
        if self.whitelist is not None and user_id in self.whitelist:
            return BYPASS_ENTITY
        if self.permission is not None and (await self.permission(bot, event)):
            return BYPASS_ENTITY
        return f"u`{user_id}`"


class PublicScope(CooldownEntity):
    def __init__(
        self,
        *,
        whitelist: Optional[Tuple[_IdType, ...]] = None,
        permission: Optional[Permission] = None
    ) -> None:
        if whitelist is not None:
            self.whitelist = tuple(str(x) for x in whitelist)
        else:
            self.whitelist = None
        self.permission = permission

    async def get_entity_id(self, bot: Bot, event: Event) -> str:
        sess = await get_session(bot, event)
        if sess is None or sess.scene.is_private:
            return BYPASS_ENTITY

        user_id = sess.user.id
        if self.whitelist is not None and user_id in self.whitelist:
            return BYPASS_ENTITY
        if self.permission is not None and (await self.permission(bot, event)):
            return BYPASS_ENTITY
        return f"u`{user_id}`"
