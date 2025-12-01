from nonebot.adapters.onebot.v11.message import MessageSegment

from ..uniseg import Other
from ..uniseg import Reference
from ..uniseg import At as UniAt
from ..uniseg import Emoji, Hyper
from ..typings import SegmentPattern
from ..uniseg import AtAll as UniAtAll
from ..uniseg import Image as UniImage
from ..uniseg import Reply as UniReply
from ..uniseg import Video as UniVideo
from ..uniseg import Voice as UniVoice

Anonymous = SegmentPattern("anonymous", MessageSegment, Other, MessageSegment.anonymous)
At = SegmentPattern(
    "at",
    MessageSegment,
    UniAt,
    MessageSegment.at,
    additional=lambda x: x.origin is not None and x.origin.data["qq"] != "all",
)
AtAll = SegmentPattern(
    "at",
    MessageSegment,
    UniAtAll,
    lambda: MessageSegment.at("all"),
    additional=lambda x: x.origin is not None and x.origin.data["qq"] == "all",
)
Contact = SegmentPattern("contact", MessageSegment, Other, MessageSegment.contact)
Dice = SegmentPattern("dice", MessageSegment, Other, MessageSegment.dice)
Face = SegmentPattern("face", MessageSegment, Emoji, MessageSegment.face)
Forward = SegmentPattern("forward", MessageSegment, Reference, MessageSegment.forward)
Image = SegmentPattern("image", MessageSegment, UniImage, MessageSegment.image)
Json = SegmentPattern("json", MessageSegment, Hyper, MessageSegment.json)
Location = SegmentPattern("location", MessageSegment, Other, MessageSegment.location)
Music = SegmentPattern("music", MessageSegment, Other, MessageSegment.music)
Node = SegmentPattern("node", MessageSegment, Other, MessageSegment.node)
Poke = SegmentPattern("poke", MessageSegment, Other, MessageSegment.poke)
Record = SegmentPattern("record", MessageSegment, UniVoice, MessageSegment.record)
Reply = SegmentPattern("reply", MessageSegment, UniReply, MessageSegment.reply)
RPS = SegmentPattern("rps", MessageSegment, Other, MessageSegment.rps)
Shake = SegmentPattern("shake", MessageSegment, Other, MessageSegment.shake)
Share = SegmentPattern("share", MessageSegment, Other, MessageSegment.share)
Video = SegmentPattern("video", MessageSegment, UniVideo, MessageSegment.video)
Xml = SegmentPattern("xml", MessageSegment, Hyper, MessageSegment.xml)
