import re
from collections import defaultdict

from nonebot import on_command, on_regex
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment
from nonebot.params import CommandArg

from .models import Option
from .drawer import draw_anan, draw_trial
from .utils import get_statement, get_character


usage = """
安安说 [文本] [表情]
    表情可选：害羞, 生气, 病娇, 无语, 开心
切换角色 [角色名]
    角色名可选：艾玛, 希罗
发送格式如下的消息以生成审判表情包：
【疑问/反驳/伪证/赞同】这是一个选项文本
可发送多行以添加多个选项
""".strip()

__plugin_meta__ = PluginMetadata(
    name="魔裁 Memes",
    description="生成「魔法少女的魔法审判」的表情包",
    usage=usage,
    type="application",
    homepage="https://github.com/zhaomaoniu/nonebot-plugin-manosaba-memes",
)

# 每个用户对应一个角色，默认艾玛
CHARACTER_MAP = defaultdict(lambda: get_character("艾玛"))

# =========================
# 1. 安安说
# =========================

# 命令：安安说 / anan说 / anansays
anan_says_handler = on_command(
    "安安说",
    aliases={"anan说", "anansays"},
    block=True,
    priority=11,
)


@anan_says_handler.handle()
async def handle_anan_says(
    bot: Bot,
    event: Event,
    args: Message = CommandArg(),
):
    """
    原来用 Alconna 的：
        Args["text", str]["face", str, None]
    现在自己从纯文本里解析：
        - 最后一个词是表情（在允许列表里）就当作 face
        - 其余当作 text
    """
    raw = args.extract_plain_text().strip()
    if not raw:
        await anan_says_handler.finish(
            "用法：安安说 [文本] [表情]\n表情可选：害羞, 生气, 病娇, 无语, 开心"
        )

    parts = raw.split()
    face_candidates = {"害羞", "生气", "病娇", "无语", "开心"}

    face = None
    text = raw

    # 如果最后一个词是合法表情，就把它当成 face
    if parts[-1] in face_candidates:
        face = parts[-1]
        text = " ".join(parts[:-1]) or face  # 避免空字符串

    # 兼容 “\n” 输入
    text = text.replace("\\n", "\n")

    image_bytes = draw_anan(text, face)
    # OneBot v11 的 MessageSegment.image 支持 bytes 作为 file
    await anan_says_handler.finish(MessageSegment.image(image_bytes))


# =========================
# 2. 审判表情：多行【疑问】xxx
# =========================

trail_handler = on_regex(
    r"^【(疑问|反驳|伪证|赞同)】(.+)$",
    flags=re.MULTILINE,
    block=True,
    priority=11,
)


@trail_handler.handle()
async def handle_trail(bot: Bot, event: Event):
    plain = event.get_message().extract_plain_text()
    matches = re.findall(
        r"^【(疑问|反驳|伪证|赞同)】(.+)$",
        plain,
        flags=re.M,
    )

    if not matches:
        # 理论上 on_regex 匹配到了就不会空，这里防御一下
        await trail_handler.finish("没有识别到有效的选项行。")

    options = []
    for statement_type, text in matches:
        statement_enum = get_statement(statement_type)
        options.append(Option(statement_enum, text))

    try:
        image_bytes = draw_trial(CHARACTER_MAP[event.get_user_id()], options)
    except OverflowError:
        await trail_handler.finish("选项过多，请减少选项数量")

    await trail_handler.finish(MessageSegment.image(image_bytes))


# =========================
# 3. 切换角色
# =========================

switch_character_handler = on_command(
    "切换角色",
    block=True,
    priority=11,
)


@switch_character_handler.handle()
async def handle_switch_character(
    bot: Bot,
    event: Event,
    args: Message = CommandArg(),
):
    global CHARACTER_MAP

    character_name = args.extract_plain_text().strip()
    if not character_name:
        await switch_character_handler.finish(
            "用法：切换角色 [角色名]\n角色名可选：艾玛, 希罗"
        )

    try:
        CHARACTER_MAP[event.get_user_id()] = get_character(character_name)
        await switch_character_handler.finish(f"已切换角色为 {character_name}")
    except KeyError:
        await switch_character_handler.finish(
            f"角色名 {character_name} 无效，请选择 艾玛 或 希罗"
        )
